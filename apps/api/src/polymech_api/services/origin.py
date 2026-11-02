"""Mac side of the Origin integration: build plot jobs from analysis runs, talk to the
Windows Bridge over HTTP, download and archive the real Origin output (SPEC §6)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from polymech_api.secrets_store import get_secret
from polymech_api.services.analysis import SOFTWARE_VERSION, load_table, run_curves
from polymech_database.models import AnalysisRun, OriginJob
from polymech_mechanics.errors import InvalidInputError
from polymech_plotting.render import to_display
from polymech_plotting.spec import (
    THESIS_BLUE,
    THESIS_RED,
    AxisSpec,
    PanelSpec,
    PlotSpec,
    SeriesSource,
)
from polymech_plotting.templates import TEMPLATES

ClientFactory = Callable[[str, float], httpx.Client]


class OriginUnavailableError(Exception):
    """Bridge not configured / unreachable / rejected the request (HTTP 503 for the UI)."""


def default_client(base_url: str, timeout: float) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=timeout, trust_env=False)


# --------------------------------------------------------------------------- VM status
def vm_status() -> list[dict[str, Any]]:
    """Parallels VMs via prlctl when available (diagnostic only; never required)."""
    prlctl = shutil.which("prlctl") or (
        "/usr/local/bin/prlctl" if Path("/usr/local/bin/prlctl").exists() else None
    )
    if prlctl is None:
        return []
    try:
        out = subprocess.run(
            [prlctl, "list", "--all", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return [
            {"name": v.get("name"), "status": v.get("status"), "ip": v.get("ip_configured")}
            for v in json.loads(out)
        ]
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return []


def pair_via_prlctl(vm_name: str) -> tuple[str, str]:
    """Read the bridge endpoint and token from the VM with prlctl (deployment helper only;
    pasting the token manually in Settings works without prlctl). Returns (url, token)."""
    prlctl = shutil.which("prlctl") or "/usr/local/bin/prlctl"
    if not Path(prlctl).exists():
        raise OriginUnavailableError("未找到 prlctl，请在设置中手动填写 Bridge 地址和 Token")

    def run(cmd: str) -> str:
        r = subprocess.run(
            [prlctl, "exec", vm_name, "cmd", "/c", cmd],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return r.stdout.strip()  # `query user` exits 1 even on success; emptiness is the check

    users = run("query user")
    user = next((ln.split()[0].lstrip(">") for ln in users.splitlines() if "console" in ln), "")
    if not user or not re.fullmatch(r"[A-Za-z0-9._-]+", user):
        raise OriginUnavailableError("虚拟机中没有已登录的用户，无法配对")
    root = rf"C:\Users\{user}\AppData\Local\PolyMechBridge"
    url = run(rf'type "{root}\bridge-endpoint.txt"').splitlines()
    token = run(rf'type "{root}\token.txt"')
    if not url or not token:
        raise OriginUnavailableError("Bridge 尚未在虚拟机中启动过（没有地址或 Token 文件）")
    return url[0].strip(), token


# --------------------------------------------------------------------------- job building
def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-.")
    return s[:40] or fallback


def file_stem(material: str, material_id: int, test_type: str, run: AnalysisRun) -> str:
    """MaterialID_TestType_Date_AnalysisVersion (SPEC §6.6)."""
    created = (
        run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=UTC)
    )  # SQLite drops tz
    date = created.astimezone().strftime("%Y%m%d")  # local calendar date
    return f"{_slug(material, f'MAT{material_id}')}_{test_type}_{date}_{run.method}-v{run.version}"


def _num(values: np.ndarray, factor: float = 1.0, offset: float = 0.0) -> list[float | None]:
    return [None if not np.isfinite(v) else float(v) * factor + offset for v in values]


def build_job(
    data_dir: Path, run: AnalysisRun, material_name: str, template_id: str, exports: list[str]
) -> dict[str, Any]:
    t = TEMPLATES.get(template_id)
    if t is None or t.x_key is None or t.y_key is None:
        raise InvalidInputError(f"模板 {template_id} 不能用于单个分析结果")
    exp = run.experiment
    sp = exp.specimen
    curves = run_curves(data_dir, run)
    if t.x_key not in curves or t.y_key not in curves:
        raise InvalidInputError(f"该分析没有模板“{t.name}”所需的数据（{t.x_key}/{t.y_key}）")

    # Raw Data: the archived original table, columns and units exactly as imported
    raw_cols: list[dict[str, Any]] = []
    if exp.raw_files:
        rf = exp.raw_files[0]
        table = load_table(data_dir, rf)
        for c in table.columns:
            raw_cols.append(
                {
                    "long_name": c.name,
                    "units": c.unit_text or "",
                    "comments": "原始数据（未修改）",
                    "designation": "X" if c.index == 0 else "Y",
                    "values": _num(c.values),
                }
            )

    # Processed Data: analysis curves converted to the template's display units
    fx, ox = t.x.factor_offset
    fy, oy = t.y.factor_offset
    n = min(len(curves[t.x_key]), len(curves[t.y_key]))
    proc = [
        {
            "long_name": t.x.label,
            "units": t.x.unit,
            "designation": "X",
            "values": _num(curves[t.x_key][:n], fx, ox),
        },
        {"long_name": t.y.label, "units": t.y.unit, "values": _num(curves[t.y_key][:n], fy, oy)},
    ]
    if t.y2 is not None and t.y2_key and t.y2_key in curves:
        f2, o2 = t.y2.factor_offset
        proc.append(
            {
                "long_name": t.y2.label,
                "units": t.y2.unit,
                "values": _num(curves[t.y2_key][:n], f2, o2),
            }
        )

    summary_q: list[str] = []
    summary_v: list[float | None] = []
    summary_u: list[str] = []
    for p in run.properties:
        if p.value is not None:
            pc = p.conditions or {}
            tags = [str(pc[k]) for k in ("tg_definition", "frequency_hz") if pc.get(k) is not None]
            if p.quantity != "glass_transition_temperature" and "deformation_mode" in pc:
                tags += [f"T={pc['temperature_k']} K"] if pc.get("temperature_k") else []
            summary_q.append(f"{p.quantity} ({', '.join(tags)})" if tags else p.quantity)
            summary_v.append(float(p.value))
            summary_u.append(p.unit)
    if not summary_q:
        summary_q, summary_v, summary_u = ["status"], [None], [run.status]

    meta = {
        "material": sp.material_id,
        "specimen": sp.label,
        "test_type": exp.test_type,
        "analysis_run_id": run.id,
        "analysis_method": run.method,
        "analysis_version": run.version,
        "analysis_status": run.status,
        "software_version": run.software_version,
        "input_sha256": run.input_sha256,
        "result_sha256": run.result_sha256,
        "raw_file_sha256": run.inputs.get("raw_file_sha256", ""),
        "template": f"{t.id} {t.version}",
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **{k: v for k, v in run.inputs.get("geometry", {}).items() if v is not None},
    }
    books = []
    if raw_cols:
        books.append(
            {
                "name": "RawData",
                "long_name": "Raw Data",
                "sheets": [{"name": "Raw", "columns": raw_cols}],
            }
        )
    books += [
        {
            "name": "Processed",
            "long_name": "Processed Data",
            "sheets": [{"name": "Curves", "columns": proc}],
        },
        {
            "name": "Summary",
            "long_name": "Summary",
            "sheets": [
                {
                    "name": "Results",
                    "columns": [
                        {"long_name": "Quantity", "designation": "L", "values": summary_q},
                        {"long_name": "Value (SI)", "values": summary_v},
                        {"long_name": "Unit", "designation": "L", "values": summary_u},
                    ],
                }
            ],
        },
        {
            "name": "Metadata",
            "long_name": "Metadata",
            "sheets": [
                {
                    "name": "Meta",
                    "columns": [
                        {"long_name": "Key", "designation": "L", "values": list(meta)},
                        {
                            "long_name": "Value",
                            "designation": "L",
                            "values": [str(v) for v in meta.values()],
                        },
                    ],
                }
            ],
        },
    ]
    kind = {"line": "line", "scatter": "scatter", "line+markers": "linesymbol"}[t.kind]
    plots = [
        {
            "book": "Processed",
            "x": 0,
            "y": 1,
            "kind": kind,
            "color": THESIS_BLUE,
            "line_width_pt": 3.0,
            "symbol": t.marker
            if t.marker in ("circle", "square", "triangle", "diamond")
            else "none",
        }
    ]
    graph: dict[str, Any] = {
        "name": "Graph1",
        "long_name": t.name,
        "template": thesis_template(t.origin_template),
        "x": {"title": t.x.title, "scale": "log10" if t.x.scale == "log" else "linear"},
        "y": {"title": t.y.title, "scale": "log10" if t.y.scale == "log" else "linear"},
        "plots": plots,
    }
    if len(proc) == 3 and t.y2 is not None:
        graph["y2"] = {"title": t.y2.title, "scale": "linear"}
        plots.append(
            {
                "book": "Processed",
                "x": 0,
                "y": 2,
                "kind": "line",
                "color": THESIS_RED,
                "line_width_pt": 3.0,
                "axis": "y2",
            }
        )
    return {
        "file_stem": file_stem(material_name, sp.material_id, exp.test_type, run),
        "books": books,
        "graphs": [graph],
        "exports": exports,
        "image_width_px": THESIS_PNG_WIDTH_PX,
        "verify": True,
    }


# --------------------------------------------------------------------------- Plot Studio
# Default Origin templates follow the default figure style (DECISIONS 2026-10-27): the thesis
# variants of the journal templates; Origin's page (10.72 in wide) at 300 dpi = 3216 px, the
# size of the user's thesis figures.
THESIS_PNG_WIDTH_PX = 3216
_ORIGIN_KIND = {"line": "line", "scatter": "scatter", "line+markers": "linesymbol"}
_ORIGIN_SYMBOLS = {"circle", "square", "triangle", "diamond"}  # cross has no Origin mapping yet


def thesis_template(journal_id: str) -> str:
    """pm_line → pm_thesis_line (registered in templates/origin/registry.json)."""
    return (
        journal_id.replace("pm_", "pm_thesis_", 1) if journal_id.startswith("pm_") else journal_id
    )


def _panel_template(panel: PanelSpec, thesis: bool) -> str:
    kinds = {s.kind for s in panel.series if s.visible}
    if panel.y2 is not None and any(s.y_axis == "y2" and s.visible for s in panel.series):
        base = "pm_doubley"
    elif kinds == {"line"}:
        base = "pm_line"
    elif kinds == {"scatter"}:
        base = "pm_scatter"
    else:
        base = "pm_linesymb"
    return thesis_template(base) if thesis else base


def _origin_axis(a: AxisSpec) -> dict[str, Any]:
    return {
        "title": a.title,
        "scale": "log10" if a.scale == "log" else "linear",
        "min": a.min,
        "max": a.max,
    }


def build_plot_job(
    spec: PlotSpec,
    resolve: Callable[[SeriesSource], tuple[np.ndarray, np.ndarray, np.ndarray | None]],
    name: str,
    exports: list[str],
    run_labels: dict[int, str],
) -> dict[str, Any]:
    """A Plot Studio figure as an Origin project: one workbook and one graph page per panel.
    Every series' points (full resolution, display units) go into its own X/Y(/error) columns
    and the graph plots those columns, so the figure stays editable and linked to its data.
    Colours follow PlotSpec.color_of (same as the Matplotlib export and the preview)."""
    thesis = bool(spec.style.palette_by_count)  # saved figures from before 2026-10-27: journal
    books: list[dict[str, Any]] = []
    graphs: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    for k, panel in enumerate(spec.panels):
        n_visible = sum(s.visible for s in panel.series)
        if not n_visible:
            continue
        letter = chr(ord("A") + k)
        book = f"Data{letter}"
        cols: list[dict[str, Any]] = []
        plots: list[dict[str, Any]] = []
        for i, s in enumerate(panel.series):
            if not s.visible:
                continue
            x, y, err = resolve(s.source)
            on_y2 = s.y_axis == "y2" and panel.y2 is not None
            yax = panel.y2 if on_y2 and panel.y2 is not None else panel.y
            src = (
                f"分析 #{s.source.run_id} {run_labels.get(s.source.run_id, '')}".strip()
                if s.source.run_id is not None
                else "图中直接输入的数据"
            )
            # no column comments: Origin's automatic legend shows Comments when present, and
            # the legend must show the series name; sources go to the Metadata book instead
            cx = len(cols)
            cols.append(
                {
                    "long_name": panel.x.label,
                    "units": panel.x.unit,
                    "designation": "X",
                    "values": _num(to_display(x, panel.x)),
                }
            )
            cols.append(
                {"long_name": s.name, "units": yax.unit, "values": _num(to_display(y, yax))}
            )
            sources[f"({chr(ord('a') + k)}) {s.name}"] = f"{yax.label}；{src}"
            yerr = None
            if s.error_bars and err is not None:
                cols.append(
                    {
                        "long_name": f"{s.name} 误差",
                        "units": yax.unit,
                        "designation": "E",
                        "values": _num(err * yax.factor_offset[0]),
                    }
                )
                yerr = len(cols) - 1
            plots.append(
                {
                    "book": book,
                    "x": cx,
                    "y": cx + 1,
                    "yerr": yerr,
                    "kind": _ORIGIN_KIND[s.kind],
                    "color": spec.color_of(i, s, n_visible),
                    "line_width_pt": s.line_width,
                    "line_style": s.line_style,
                    "symbol": s.marker if s.marker in _ORIGIN_SYMBOLS else "none",
                    "symbol_size": s.marker_size,
                    "symbol_filled": s.marker_filled,
                    "axis": "y2" if on_y2 else "y",
                }
            )
        label = f"({chr(ord('a') + k)})"
        books.append(
            {
                "name": book,
                "long_name": f"面板 {label} 数据",
                "sheets": [{"name": "Data", "columns": cols}],
            }
        )
        graph: dict[str, Any] = {
            "name": f"Fig{letter}",
            "long_name": panel.title or f"{name or '图'} {label}",
            "template": _panel_template(panel, thesis),
            "x": _origin_axis(panel.x),
            "y": _origin_axis(panel.y),
            "plots": plots,
            "legend": panel.legend.show,
        }
        if panel.y2 is not None and any(p["axis"] == "y2" for p in plots):
            graph["y2"] = _origin_axis(panel.y2)
        graphs.append(graph)
    if not graphs:
        raise InvalidInputError("图中没有可见的数据系列，无法导出到 Origin")
    runs = sorted(
        {rid for p in spec.panels for s in p.series if (rid := s.source.run_id) is not None}
    )
    meta = {
        "figure": name or spec.template_id,
        "panels": str(len(graphs)),
        "source_runs": "; ".join(f"#{r} {run_labels.get(r, '')}".strip() for r in runs) or "—",
        "origin_templates": ", ".join(g["template"] for g in graphs),
        "data": "图中实际绘制的点（全分辨率，显示单位）",
        "plot_spec_version": spec.spec_version,
        "software_version": SOFTWARE_VERSION,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **sources,
    }
    books.append(
        {
            "name": "Metadata",
            "long_name": "Metadata",
            "sheets": [
                {
                    "name": "Meta",
                    "columns": [
                        {"long_name": "Key", "designation": "L", "values": list(meta)},
                        {"long_name": "Value", "designation": "L", "values": list(meta.values())},
                    ],
                }
            ],
        }
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return {
        "file_stem": f"{_slug(name, 'figure')}_{stamp}",
        "books": books,
        "graphs": graphs,
        "exports": exports,
        "image_width_px": THESIS_PNG_WIDTH_PX,
        "verify": True,
    }


# --------------------------------------------------------------------------- bridge calls
class BridgeClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        timeout: float = 30,
        factory: ClientFactory = default_client,
        local: bool = False,
    ):
        if not base_url:
            raise OriginUnavailableError(
                "尚未设置 Windows Bridge 地址，请在“设置 → Origin Bridge”中填写"
            )
        self.http = factory(base_url.rstrip("/"), timeout)
        self.token = token
        self.local = local

    def _req(self, method: str, path: str, auth: bool = True, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        try:
            r = self.http.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as e:
            if self.local:
                raise OriginUnavailableError(
                    f"本机 Origin 组件暂未响应（{type(e).__name__}）。首次启动或绘图可能较慢，请稍候重试；"
                    "若持续失败，请查看本机 Origin 日志与许可状态。"
                ) from e
            raise OriginUnavailableError(
                f"无法连接 Windows Bridge（{type(e).__name__}）。请检查：虚拟机是否运行、Bridge 是否已启动、"
                "地址是否正确、Windows 防火墙是否放行。"
            ) from e
        if r.status_code == 401:
            if self.local:
                raise OriginUnavailableError(
                    "本机 Origin 组件认证已失效，请重新启动 PolyMech Studio。"
                )
            raise OriginUnavailableError(
                "Bridge 拒绝了认证 Token，请重新配对（设置 → Origin Bridge）"
            )
        if r.status_code >= 400:
            detail = (
                r.json().get("detail")
                if r.headers.get("content-type", "").startswith("application/json")
                else r.text
            )
            raise OriginUnavailableError(f"Bridge 返回错误 {r.status_code}：{detail}")
        return r

    def health(self) -> dict[str, Any]:
        out: dict[str, Any] = self._req("GET", "/health", auth=False).json()
        return out

    def capabilities(self) -> dict[str, Any]:
        out: dict[str, Any] = self._req("GET", "/v1/capabilities").json()
        return out

    def submit(self, job: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = self._req("POST", "/v1/plot-jobs", json=job).json()
        return out

    def status(self, job_id: str) -> dict[str, Any]:
        out: dict[str, Any] = self._req("GET", f"/v1/plot-jobs/{job_id}").json()
        return out

    def download(self, job_id: str, name: str) -> bytes:
        return self._req("GET", f"/v1/plot-jobs/{job_id}/artifacts/{name}").content


def make_client(settings: dict[str, Any], factory: ClientFactory = default_client) -> BridgeClient:
    return BridgeClient(
        settings.get("bridge_url", ""),
        get_secret("bridge_token"),
        float(settings.get("bridge_timeout_s", 30)) or 30,
        factory,
    )


def refresh_job(data_dir: Path, job: OriginJob, client: BridgeClient) -> None:
    """Poll the bridge; when finished, download every artifact into data_dir/origin/<id>/."""
    if job.status in ("done", "failed", "cancelled") or not job.bridge_job_id:
        return
    st = client.status(job.bridge_job_id)
    job.status = st["status"]
    job.error = st.get("error", "")
    if st["status"] in ("done", "failed"):
        target = data_dir / "origin" / f"job{job.id}"
        target.mkdir(parents=True, exist_ok=True)
        for name in st.get("artifacts", []):
            (target / name).write_bytes(client.download(job.bridge_job_id, name))
        made = st.get("result", {}).get("made", {})
        if made.get("opju") and (target / made["opju"]).exists():
            job.opju_path = f"origin/job{job.id}/{made['opju']}"
        pngs = made.get("exports", {}).get("png", [])
        if pngs:
            job.png_path = f"origin/job{job.id}/{pngs[0]}"
        job.verification = st.get("result", {}).get("verification", {}) | {
            "export_errors": made.get("export_errors", {}),
            "origin": st.get("result", {}).get("origin", {}),
        }
        job.finished_at = datetime.now(UTC)
