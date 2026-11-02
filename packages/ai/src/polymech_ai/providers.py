"""LLM providers with one interface (SPEC §8.5): Codex CLI (default), Claude Code CLI, API.

CLI flags below were taken from the local `--help` output (codex-cli 0.163.0-alpha.11.2,
Claude Code 2.1.303; see docs/DECISIONS.md). Reasoning effort: Codex config override
`model_reasoning_effort`, Claude `--effort`, Anthropic API `output_config.effort`,
OpenAI-compatible `reasoning_effort`; empty = the provider's own default. CLIs run as subprocesses without a shell, with a
timeout, in an empty temporary directory, with tools disabled (Claude: --tools "") or the
read-only sandbox (Codex). CLI providers still send content to cloud models.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse

import anthropic
import httpx
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

# Levels accepted by every provider (Codex additionally has none/minimal, the others don't).
Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


def _check_effort(effort: str) -> str:
    if effort and effort not in EFFORTS:
        raise ValueError(f"未知的推理强度：{effort}")
    return effort


class ProviderError(Exception):
    """Provider unavailable, timed out or returned an unusable response."""


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    installed: bool
    version: str = ""
    logged_in: bool | None = None  # None = unknown
    detail: str = ""


@dataclass(frozen=True)
class RawCompletion:
    data: Any  # parsed JSON object (not yet schema-validated)
    provider: str
    model: str
    elapsed_s: float
    usage: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def status(self) -> ProviderStatus: ...

    def complete(self, prompt: str, schema: dict[str, Any], timeout_s: float) -> RawCompletion: ...


PROXY_VARS = (
    "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
    "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
)  # fmt: skip
_network_env: dict[str, str] = {}


def set_network_env(env: dict[str, str]) -> None:
    """Proxy settings for AI calls only (the desktop app takes them from the login shell; an app
    started from Finder has none, so CLIs and APIs behind a proxy time out). Kept out of the
    backend's own environment so local connections such as the Origin Bridge stay direct."""
    _network_env.clear()
    _network_env.update({k: v for k, v in env.items() if k in PROXY_VARS and v})


def _proxy_for(url: str) -> str | None:
    """Proxy for an API URL from the AI network settings, honouring no_proxy; None = direct.
    Only the settings passed to set_network_env apply (the process environment is already
    honoured by the HTTP clients themselves)."""
    env = _network_env
    proxy = next(
        (env[k] for k in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY") if k in env), None
    )
    host = (urlparse(url).hostname or "").lower()
    if not proxy or not host:
        return None
    for entry in (env.get("no_proxy") or env.get("NO_PROXY") or "").split(","):
        e = entry.strip().lower().lstrip(".")
        if e == "*" or (e and (host == e or host.endswith("." + e))):
            return None
    return proxy


def _find(binary: str) -> str | None:
    if sys.platform == "win32":
        return shutil.which(binary + ".exe") or shutil.which(binary)
    return shutil.which(binary) or next(
        (
            str(p)
            for p in (Path.home() / ".local/bin" / binary, Path("/opt/homebrew/bin") / binary)
            if p.exists()
        ),
        None,
    )


def _run(
    cmd: list[str], stdin: str, timeout_s: float, cwd: str
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("POLYMECH_")}
    env = {**_network_env, **env}  # the process's own settings win
    try:
        if sys.platform == "win32":
            executable = Path(cmd[0])
            if executable.suffix.lower() in (".cmd", ".bat"):
                # npm shims are replaced by their Node entry point. No cmd.exe quoting or shell.
                entries = {
                    "codex": "@openai/codex/bin/codex.js",
                    "claude": "@anthropic-ai/claude-code/cli.js",
                }
                entry = entries.get(executable.stem.lower())
                script = executable.parent / "node_modules" / entry if entry else None
                node = shutil.which("node.exe")
                if script is None or not script.is_file() or node is None:
                    raise ProviderError("无法解析 CLI 的 npm 启动脚本，请安装原生 CLI 或 Node.js。")
                cmd = [node, str(script), *cmd[1:]]
            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as proc:
                try:
                    stdout, stderr = proc.communicate(stdin, timeout=timeout_s)
                    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
                finally:
                    if proc.poll() is None:
                        subprocess.run(
                            ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                            timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        proc.communicate(timeout=10)
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=cwd,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ProviderError(f"调用超时（{timeout_s:.0f} s）") from e
    except OSError as e:
        raise ProviderError(f"无法启动 {cmd[0]}：{e.strerror}") from e


class CodexCLI:
    name = "codex"

    def __init__(self, model: str = "", effort: str = "") -> None:
        self.model = model
        self.effort = _check_effort(effort)
        self.bin = _find("codex")

    def status(self) -> ProviderStatus:
        if not self.bin:
            return ProviderStatus(self.name, False, detail="未找到 codex 命令")
        ver = _run([self.bin, "--version"], "", 20, tempfile.gettempdir()).stdout.strip()
        login = _run([self.bin, "login", "status"], "", 20, tempfile.gettempdir())
        text = (login.stdout + login.stderr).strip()
        return ProviderStatus(
            self.name, True, ver, login.returncode == 0 and "Logged in" in text, text[:200]
        )

    def complete(self, prompt: str, schema: dict[str, Any], timeout_s: float) -> RawCompletion:
        if not self.bin:
            raise ProviderError("未安装 Codex CLI")
        with tempfile.TemporaryDirectory(prefix="polymech-ai-") as tmp:
            work = Path(tmp) / "empty"
            work.mkdir()
            (Path(tmp) / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
            out = Path(tmp) / "out.json"
            cmd = [
                self.bin,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--output-schema",
                str(Path(tmp) / "schema.json"),
                "-o",
                str(out),
                "-C",
                str(work),
                "--color",
                "never",
            ]
            if self.model:
                cmd += ["-m", self.model]
            if self.effort:
                cmd += ["-c", f'model_reasoning_effort="{self.effort}"']
            t0 = time.perf_counter()
            r = _run([*cmd, "-"], prompt, timeout_s, str(work))
            elapsed = time.perf_counter() - t0
            if r.returncode != 0 or not out.exists():
                raise ProviderError(
                    f"Codex 返回错误（退出码 {r.returncode}）：{r.stderr.strip()[-300:]}"
                )
            text = out.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("Codex 输出不是合法 JSON") from e
        usage = {}
        for line in r.stderr.splitlines()[::-1]:
            if line.replace(",", "").strip().isdigit():
                usage["tokens"] = int(line.replace(",", "").strip())
                break
        return RawCompletion(data, self.name, self.model or "codex-default", elapsed, usage)


class ClaudeCLI:
    name = "claude"

    def __init__(self, model: str = "", effort: str = "") -> None:
        self.model = model
        self.effort = _check_effort(effort)
        self.bin = _find("claude")

    def status(self) -> ProviderStatus:
        if not self.bin:
            return ProviderStatus(self.name, False, detail="未找到 claude 命令")
        ver = _run([self.bin, "--version"], "", 20, tempfile.gettempdir()).stdout.strip()
        st = _run([self.bin, "auth", "status"], "", 20, tempfile.gettempdir())
        try:
            logged = bool(json.loads(st.stdout).get("loggedIn"))
        except json.JSONDecodeError:
            logged = None
        return ProviderStatus(self.name, True, ver, logged, "")

    def complete(self, prompt: str, schema: dict[str, Any], timeout_s: float) -> RawCompletion:
        if not self.bin:
            raise ProviderError("未安装 Claude Code CLI")
        cmd = [
            self.bin,
            "-p",
            "--tools",
            "",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        with tempfile.TemporaryDirectory(prefix="polymech-ai-") as tmp:
            t0 = time.perf_counter()
            r = _run(cmd, prompt, timeout_s, tmp)
            elapsed = time.perf_counter() - t0
        if r.returncode != 0:
            detail = r.stderr.strip()[-300:]
            try:  # with --output-format json the reason is in the stdout envelope
                detail = str(json.loads(r.stdout).get("result", ""))[:300] or detail
            except json.JSONDecodeError:
                detail = detail or r.stdout.strip()[-300:]
            raise ProviderError(f"Claude CLI 返回错误（退出码 {r.returncode}）：{detail}")
        try:
            env = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise ProviderError("Claude CLI 输出不是合法 JSON") from e
        if env.get("is_error"):
            raise ProviderError(f"Claude CLI 报告错误：{str(env.get('result'))[:300]}")
        data = env.get("structured_output")
        if data is None:
            try:
                data = json.loads(env.get("result", ""))
            except (TypeError, json.JSONDecodeError) as e:
                raise ProviderError("Claude CLI 没有返回结构化输出") from e
        models = list((env.get("modelUsage") or {}).keys())
        usage = {"cost_usd": env.get("total_cost_usd"), "model_usage": env.get("modelUsage")}
        return RawCompletion(
            data,
            self.name,
            models[0] if models else (self.model or "claude-default"),
            elapsed,
            usage,
        )


class AnthropicAPI:
    """Anthropic Messages API via the official SDK; JSON via structured outputs
    (`output_config.format`) — current models reject a forced tool_choice."""

    name = "anthropic_api"
    DEFAULT_MODEL = "claude-opus-5-5"
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def __init__(
        self,
        api_key: str | None,
        model: str = "",
        base_url: str = "",
        effort: str = "",
    ) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.effort = _check_effort(effort)

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.name,
            True,
            self.model,
            bool(self.api_key),
            "API Key 已配置" if self.api_key else "未配置 API Key（环境变量或钥匙串）",
        )

    def complete(self, prompt: str, schema: dict[str, Any], timeout_s: float) -> RawCompletion:
        if not self.api_key:
            raise ProviderError("未配置 Anthropic API Key")
        proxy = _proxy_for(self.base_url)
        client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout_s,
            max_retries=1,
            http_client=anthropic.DefaultHttpxClient(proxy=proxy) if proxy else None,
        )
        output_config: BetaOutputConfigParam = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = cast(Effort, self.effort)
        messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
        # on a classifier decline, retry server-side on Anthropic's recommended model
        # (Claude API only; a custom base URL may be a proxy that does not support it)
        fallback = self.base_url.rstrip("/") == self.DEFAULT_BASE_URL
        fallbacks: Literal["default"] | anthropic.Omit = "default" if fallback else anthropic.omit
        t0 = time.perf_counter()
        try:
            msg = client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                messages=messages,
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"] if fallback else anthropic.omit,
                fallbacks=fallbacks,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic API Key 无效") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Anthropic API 速率受限，请稍后再试") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API 返回 {e.status_code}：{e.message[:200]}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"无法连接 Anthropic API：{type(e).__name__}") from e
        if msg.stop_reason == "refusal":
            category = getattr(msg.stop_details, "category", None) if msg.stop_details else None
            raise ProviderError(f"模型拒绝了该请求（类别：{category or '未说明'}）")
        if msg.stop_reason == "max_tokens":
            raise ProviderError("模型输出被 max_tokens 截断")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("Anthropic API 没有返回结构化结果")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("Anthropic API 输出不是合法 JSON") from e
        return RawCompletion(
            data,
            self.name,
            msg.model,
            time.perf_counter() - t0,
            msg.usage.model_dump() if msg.usage else {},
        )


class OpenAICompatibleAPI:
    """OpenAI-compatible /chat/completions with response_format json_schema."""

    name = "openai_api"

    def __init__(self, api_key: str | None, model: str, base_url: str, effort: str = "") -> None:
        self.api_key, self.model, self.base_url = api_key, model, base_url
        self.effort = _check_effort(effort)

    def status(self) -> ProviderStatus:
        ok = bool(self.api_key and self.model and self.base_url)
        return ProviderStatus(
            self.name, True, self.model, ok, "" if ok else "需要 API 地址、模型名和 API Key"
        )

    def complete(self, prompt: str, schema: dict[str, Any], timeout_s: float) -> RawCompletion:
        if not (self.api_key and self.model and self.base_url):
            raise ProviderError("OpenAI 兼容接口未配置完整")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema, "strict": True},
            },
        }
        if self.effort:  # only reasoning models accept it; the server's error is reported
            body["reasoning_effort"] = self.effort
        t0 = time.perf_counter()
        try:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            r = httpx.post(
                url,
                json=body,
                timeout=timeout_s,
                headers={"Authorization": f"Bearer {self.api_key}"},
                proxy=_proxy_for(url),
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"无法连接 API：{type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"API 返回 {r.status_code}")
        msg = r.json()
        try:
            data = json.loads(msg["choices"][0]["message"]["content"])
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ProviderError("API 没有返回合法 JSON") from e
        return RawCompletion(
            data,
            self.name,
            msg.get("model", self.model),
            time.perf_counter() - t0,
            msg.get("usage", {}),
        )
