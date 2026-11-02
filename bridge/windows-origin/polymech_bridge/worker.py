"""Serial Origin worker: one thread owns COM (CoInitialize) and one Origin instance it started
itself. Jobs run strictly one at a time (SPEC §6.4). Only PIDs this worker created are ever
terminated; the user's own Origin sessions are never touched."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from polymech_bridge.schema import PlotJob

log = logging.getLogger("polymech_bridge")
Status = Literal["queued", "running", "done", "failed", "cancelled"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def origin_pids() -> set[int]:
    out = subprocess.run(
        ["tasklist", "/fi", "imagename eq Origin64.exe", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        creationflags=_NO_WINDOW,
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def is_automation_instance(pid: int) -> bool:
    """True only for Origin started by COM (command line contains -Embedding)."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
    ]
    out = subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", check=False, creationflags=_NO_WINDOW
    ).stdout
    return "Origin64.exe" in out and "-Embedding" in out


def automation_instances() -> dict[int, str]:
    """PID and creation time together prevent cleanup after PID reuse."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "@(Get-CimInstance Win32_Process -Filter \"Name='Origin64.exe'\" | "
            "Where-Object {$_.CommandLine -like '*-Embedding*'} | "
            "Select-Object ProcessId,@{N='Created';E={$_.CreationDate.ToFileTimeUtc().ToString()}}) | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        creationflags=_NO_WINDOW,
    ).stdout.strip()
    rows = json.loads(out) if out else []
    if isinstance(rows, dict):
        rows = [rows]
    return {int(row["ProcessId"]): str(row["Created"]) for row in rows}


def kill_pid(pid: int, created: str) -> None:
    if automation_instances().get(pid) != created or not is_automation_instance(pid):
        log.warning("refusing to terminate pid %s: not an Origin automation instance", pid)
        return
    subprocess.run(
        ["taskkill", "/pid", str(pid), "/f"],
        capture_output=True,
        check=False,
        creationflags=_NO_WINDOW,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class JobState:
    id: str
    job: PlotJob
    dir: Path
    status: Status = "queued"
    message: str = "排队中"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    finished_at: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "artifacts": sorted(p.name for p in self.dir.iterdir() if p.is_file())
            if self.dir.exists()
            else [],
        }


class OriginWorker(threading.Thread):
    def __init__(self, work_root: Path, idle_timeout_s: float = 600, executor: Any = None) -> None:
        super().__init__(name="origin-worker", daemon=True)
        self.work_root = work_root
        self.idle_timeout_s = idle_timeout_s
        self.jobs: dict[str, JobState] = {}
        self.lock = threading.Lock()
        self.q: queue.Queue[str | None] = queue.Queue()
        self.owned: dict[int, str] = {}
        self.origin_info: dict[str, Any] = {}
        self._op: Any = None
        self._launch_done: threading.Event | None = None
        self._executor = executor  # injectable for tests of the queue logic only

    # ---------------------------------------------------------------- queue API
    def submit(self, job: PlotJob) -> JobState:
        jid = uuid.uuid4().hex[:16]
        d = self.work_root / jid
        d.mkdir(parents=True)
        st = JobState(jid, job, d)
        with self.lock:
            self.jobs[jid] = st
        self.q.put(jid)
        return st

    def get(self, jid: str) -> JobState | None:
        with self.lock:
            return self.jobs.get(jid)

    def cancel(self, jid: str) -> JobState | None:
        with self.lock:
            st = self.jobs.get(jid)
            if st is None:
                return None
            st.cancel_requested = True
            if st.status == "queued":
                st.status, st.message = "cancelled", "已取消"
            running = st.status == "running"
        if running:
            self.terminate_owned()
        return st

    def stop(self) -> None:
        self.q.put(None)

    # ---------------------------------------------------------------- Origin lifecycle
    def _ensure_origin(self) -> Any:
        if self._op is not None:
            return self._op
        before = automation_instances()
        done = threading.Event()
        self._launch_done = done

        def record_started() -> None:
            self.owned.update(
                {
                    pid: created
                    for pid, created in automation_instances().items()
                    if pid not in before
                }
            )

        def watch_start() -> None:
            # COM startup can block on licensing. Track its new process before the call returns,
            # so shutdown can still reclaim the verified instance while COM is blocked.
            while not done.wait(0.5):
                record_started()

        watcher = threading.Thread(target=watch_start, daemon=True)
        watcher.start()
        try:
            import originpro as op

            self._op = op  # retain the proxy even if COM startup raises
            op.set_show(False)  # first call launches a NEW instance (never attaches to the user's)
        finally:
            done.set()
            watcher.join(timeout=10)
            record_started()
            self._launch_done = None
        self.origin_info = {
            "version": op.lt_float("@V"),
            "owned_pids": sorted(self.owned),
            "owned_created": dict(self.owned),
        }
        log.info("started Origin %s (pids %s)", self.origin_info["version"], sorted(self.owned))
        return op

    def close_origin(self) -> None:
        if self._op is None and not self.owned:
            return
        op, self._op = self._op, None
        if op is not None:
            if op.po:  # a failed constructor may not have created an application
                try:
                    op.lt_exec("doc -s;")
                except Exception:
                    log.warning(
                        "Origin save suppression raised:\n%s", traceback.format_exc(limit=2)
                    )
                try:
                    op.exit()
                except Exception:
                    log.warning("Origin exit raised:\n%s", traceback.format_exc(limit=2))
            # originpro 1.1.15 clears APP._app only after a successful COM Exit. A crashed
            # instance raises first, leaving its shared proxy unusable for every later job.
            op.po._app = None
        deadline = time.time() + 20
        while self.owned.keys() & origin_pids() and time.time() < deadline:
            time.sleep(1)
        self.terminate_owned()

    def terminate_owned(self) -> None:
        if self._launch_done:
            self._launch_done.set()
        for pid, created in list(self.owned.items()):
            log.info("terminating owned Origin pid %s", pid)
            kill_pid(pid, created)
        self.owned = {}

    # ---------------------------------------------------------------- thread
    def run(self) -> None:
        try:
            import pythoncom
        except ImportError:
            pythoncom = None  # non-Windows: only an injected executor can run (queue tests)
        if pythoncom is not None:
            pythoncom.CoInitialize()
        try:
            while True:
                try:
                    jid = self.q.get(timeout=self.idle_timeout_s)
                except queue.Empty:
                    self.close_origin()  # idle: release the instance
                    continue
                if jid is None:
                    break
                self._run_job(jid)
        finally:
            self.close_origin()
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def _run_job(self, jid: str) -> None:
        st = self.get(jid)
        if st is None or st.status == "cancelled":
            return
        with self.lock:
            st.status, st.message = "running", "正在启动 Origin"
        try:
            if self._executor is not None:
                result = self._executor(st)
            else:
                from polymech_bridge.origin_build import build_project, verify_project, write_json

                op = self._ensure_origin()
                if st.cancel_requested:
                    raise RuntimeError("任务已取消")
                st.message = "正在写入工作表并绘图"
                made = build_project(op, st.job, st.dir)
                result = {"made": made, "origin": self.origin_info}
                if st.job.verify:
                    st.message = "正在重新打开工程核验"
                    result["verification"] = verify_project(op, st.job, st.dir / made["opju"])
                write_json(st.dir / "result.json", result)
            with self.lock:
                st.result = result
                passed = result.get("verification", {}).get("passed", True)
                st.status = "cancelled" if st.cancel_requested else "done" if passed else "failed"
                st.message = (
                    "已取消"
                    if st.cancel_requested
                    else "完成"
                    if passed
                    else "工程已保存，但重新打开核验未通过"
                )
                st.finished_at = _now()
        except Exception as e:
            log.error("job %s failed:\n%s", jid, traceback.format_exc())
            with self.lock:
                st.status = "cancelled" if st.cancel_requested else "failed"
                st.error = "" if st.cancel_requested else f"{type(e).__name__}: {e}"
                st.message = "已取消" if st.cancel_requested else "失败"
                st.finished_at = _now()
            # a COM failure may leave Origin unusable: restart it for the next job
            self.close_origin()
