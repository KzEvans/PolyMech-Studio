"""Provider request construction (no network): reasoning effort per provider, Anthropic API via
structured outputs with refusal handling. Flags match the local CLIs' --help (DECISIONS.md)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from polymech_ai import providers as pv

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def fake_run(calls: list[list[str]], stdout: str = "", write_out: bool = False):  # type: ignore[no-untyped-def]
    def run(
        cmd: list[str], stdin: str, timeout_s: float, cwd: str
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if write_out:
            Path(cmd[cmd.index("-o") + 1]).write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    return run


@pytest.mark.parametrize("effort", ["", "high"])
def test_codex_effort_is_a_config_override(monkeypatch: pytest.MonkeyPatch, effort: str) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(pv, "_run", fake_run(calls, write_out=True))
    p = pv.CodexCLI(effort=effort)
    p.bin = "codex"
    assert p.complete("x", SCHEMA, 10).data == {"ok": True}
    cmd = calls[0]
    if effort:
        assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="high"'
    else:
        assert "-c" not in cmd


def test_claude_effort_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    envelope = json.dumps({"structured_output": {"ok": True}, "modelUsage": {"claude-x": {}}})
    monkeypatch.setattr(pv, "_run", fake_run(calls, stdout=envelope))
    p = pv.ClaudeCLI(effort="max")
    p.bin = "claude"
    p.complete("x", SCHEMA, 10)
    assert calls[0][calls[0].index("--effort") + 1] == "max"
    p.effort = ""
    p.complete("x", SCHEMA, 10)
    assert "--effort" not in calls[1]


def test_unknown_effort_rejected() -> None:
    with pytest.raises(ValueError, match="推理强度"):
        pv.CodexCLI(effort="extreme")
    with pytest.raises(ValueError, match="推理强度"):
        pv.AnthropicAPI("k", effort="minimal")  # Codex-only level


class FakeAnthropic:
    """Stands in for anthropic.Anthropic; records the create() arguments."""

    last: ClassVar[dict[str, Any]] = {}
    reply: ClassVar[Any] = None

    def __init__(self, **client_kw: Any) -> None:
        FakeAnthropic.last = {"client": client_kw}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        FakeAnthropic.last["request"] = kw
        return FakeAnthropic.reply


def _message(stop_reason: str = "end_turn", text: str = '{"ok": true}') -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=text)] if stop_reason != "refusal" else [],
        model="claude-opus-5-5",
        usage=SimpleNamespace(model_dump=lambda: {"output_tokens": 5}),
    )


def test_anthropic_api_structured_output_effort_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pv.anthropic, "Anthropic", FakeAnthropic)
    FakeAnthropic.reply = _message()
    res = pv.AnthropicAPI("key", effort="high").complete("prompt", SCHEMA, 30)
    req = FakeAnthropic.last["request"]
    assert res.data == {"ok": True} and res.model == "claude-opus-5-5"
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "high",
    }
    assert "tool_choice" not in req and "tools" not in req  # forced tool use 400s on current models
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert FakeAnthropic.last["client"]["api_key"] == "key"


def test_anthropic_api_custom_base_url_no_fallback_and_default_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pv.anthropic, "Anthropic", FakeAnthropic)
    FakeAnthropic.reply = _message()
    pv.AnthropicAPI("key", base_url="https://proxy.example").complete("p", SCHEMA, 30)
    req = FakeAnthropic.last["request"]
    assert "effort" not in req["output_config"]
    assert req["fallbacks"] is pv.anthropic.omit and req["betas"] is pv.anthropic.omit


@pytest.mark.parametrize(
    ("stop", "text", "msg"),
    [("refusal", "", "拒绝"), ("max_tokens", "{", "截断"), ("end_turn", "not json", "JSON")],
)
def test_anthropic_api_failures_become_provider_errors(
    monkeypatch: pytest.MonkeyPatch, stop: str, text: str, msg: str
) -> None:
    monkeypatch.setattr(pv.anthropic, "Anthropic", FakeAnthropic)
    FakeAnthropic.reply = _message(stop, text)
    with pytest.raises(pv.ProviderError, match=msg):
        pv.AnthropicAPI("key").complete("p", SCHEMA, 30)


def test_openai_compatible_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def post(url: str, json: dict[str, Any], **_: Any) -> Any:
        sent.append(json)
        body = {"choices": [{"message": {"content": '{"ok": true}'}}], "model": "m"}
        return SimpleNamespace(status_code=200, json=lambda: body)

    monkeypatch.setattr(pv.httpx, "post", post)
    pv.OpenAICompatibleAPI("k", "m", "https://x", effort="low").complete("p", SCHEMA, 10)
    pv.OpenAICompatibleAPI("k", "m", "https://x").complete("p", SCHEMA, 10)
    assert sent[0]["reasoning_effort"] == "low" and "reasoning_effort" not in sent[1]


def test_network_env_reaches_cli_and_api_but_honours_no_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop app started from Finder: proxy settings from the login shell must reach AI calls."""
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    pv.set_network_env(
        {"https_proxy": "http://127.0.0.1:7890", "no_proxy": "localhost,.lan", "PATH": "/x"}
    )
    try:
        result = pv._run(
            [
                sys.executable,
                "-c",
                "import os,json; print(json.dumps({k:os.getenv(k) for k in ['https_proxy','PATH']}))",
            ],
            "",
            5,
            ".",
        )
        seen = json.loads(result.stdout)
        assert seen["https_proxy"] == "http://127.0.0.1:7890"
        assert seen.get("PATH") != "/x"  # only proxy variables are taken over
        assert pv._proxy_for("https://api.anthropic.com/v1") == "http://127.0.0.1:7890"
        assert pv._proxy_for("http://localhost:8000/v1") is None
        assert pv._proxy_for("http://llm.lan/v1") is None
    finally:
        pv.set_network_env({})
