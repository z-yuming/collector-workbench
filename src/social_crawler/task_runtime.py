"""Bounded queue with independently cancellable worker process trees."""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from ctypes import wintypes
from contextlib import closing

from social_crawler.settings import Settings
from social_crawler.task_store import TaskStore, ACTIVE, now, public_task


class ProcessTree:
    def __init__(self, command: list[str], **kwargs):
        self.handle = None
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(command, creationflags=flags, start_new_session=os.name != "nt", **kwargs)
        if os.name == "nt":
            # KILL_ON_JOB_CLOSE also stops descendants when the app/service exits.
            class Basic(ctypes.Structure):
                _fields_ = [("per_process", ctypes.c_longlong), ("per_job", ctypes.c_longlong), ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
            class Extended(ctypes.Structure):
                _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            info = Extended(); info.basic.flags = 0x2000
            if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(self.process._handle))):
                self.process.kill(); self.process.wait()
                self.close()
                raise RuntimeError("无法建立任务进程管理，请检查本地运行权限后重试。")

    def stop(self):
        if os.name == "nt" and self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
        elif self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=10)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class TaskManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = TaskStore.for_settings(settings)
        self.store.recover()
        self.lock = threading.RLock()
        self.running = {}
        self.threads = set()
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.dispatcher = threading.Thread(target=self._dispatch, daemon=True)
        self.dispatcher.start()

    def submit(self, source, payload, request_key=None, schedule_id=None):
        if request_key:
            with closing(self.store.connect()) as db:
                existing = db.execute("SELECT id FROM tasks WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                return public_task(self.store.get(existing[0]))
        from social_crawler.preflight import check_task
        check = check_task(source, payload, self.settings)
        if not check["ready"]:
            raise ValueError(next(c["message"] for c in check["checks"] if c["status"] == "blocked"))
        payload = check["payload"]
        resource = "video" if source == "video" else "device:" + payload["serial"] if payload.get("mode") in {"adb", "ui"} else "browser"
        with self.lock:
            if schedule_id:
                existing = next((t for t in self.store.active() if t.get("scheduleId") == schedule_id), None)
                if existing:
                    return public_task(existing)
            task = self.store.create(source, payload, self.settings, resource, request_key, schedule_id)
        self.wake.set()
        return public_task(task)

    def cancel(self, task_id):
        with self.lock:
            task = self.store.get(task_id)
            if task["status"] == "queued":
                task = self.store.update(task_id, expected={"queued"}, status="cancelled", stage="已取消排队", finishedAt=now())
            elif task["status"] in {"running", "cancelling"}:
                task = self.store.update(task_id, expected={"running", "cancelling"}, status="cancelling", stage="正在停止采集进程")
        self.wake.set()
        return public_task(task)

    def _dispatch(self):
        while not self.closed.is_set():
            with self.lock:
                resources = {entry[0] for entry in self.running.values()}
                for task in self.store.active():
                    if task["status"] != "queued" or task["resource"] in resources or len(self.running) >= 2:
                        continue
                    self.store.update(task["id"], expected={"queued"}, status="running", startedAt=now(), stage="正在检查执行条件")
                    self.running[task["id"]] = (task["resource"], None)
                    resources.add(task["resource"])
                    thread = threading.Thread(target=self._run, args=(task,), daemon=True)
                    self.threads.add(thread)
                    thread.start()
            self.wake.wait(.25); self.wake.clear()

    def _run(self, task):
        tree = None
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            tree = ProcessTree([sys.executable, "-m", "social_crawler.task_worker", "--db", str(self.store.path), "--id", task["id"]], cwd=self.settings.project_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.lock:
                self.running[task["id"]] = (task["resource"], tree)
            self.store.update(task["id"], expected={"running"}, pid=tree.process.pid)
            while tree.process.poll() is None:
                if self.closed.is_set() or self.store.get(task["id"])["status"] == "cancelling":
                    tree.stop()
                    break
                time.sleep(.1)
            current = self.store.get(task["id"])
            if current["status"] == "cancelling":
                self.store.update(task["id"], expected={"cancelling"}, status="cancelled", stage="已停止任务", message="任务已取消。已生成的文件仍保留，可查看详情。", finishedAt=now())
            elif current["status"] == "running":
                self.store.update(task["id"], expected={"running"}, status="interrupted" if self.closed.is_set() else "failed", stage="任务运行中断", message="任务进程意外结束，请检查运行环境后重试。", finishedAt=now())
        except Exception as exc:
            current = self.store.get(task["id"])
            self.store.update(task["id"], expected=ACTIVE, status="cancelled" if current["status"] == "cancelling" else "failed", stage="无法完成任务", message=str(exc)[:500], finishedAt=now())
        finally:
            if tree:
                tree.close()
            with self.lock:
                self.running.pop(task["id"], None)
                self.threads.discard(threading.current_thread())
            self.wake.set()

    def close(self):
        self.closed.set(); self.wake.set()
        self.dispatcher.join(timeout=3)
        with self.lock:
            trees = [value[1] for value in self.running.values() if value[1]]
        for tree in trees:
            tree.stop()
        with self.lock:
            threads = list(self.threads)
        for thread in threads:
            thread.join(timeout=10)


_managers = {}
_manager_lock = threading.Lock()


def get_manager(settings: Settings):
    key = str((settings.log_dir.parent / "workbench/tasks.sqlite3").resolve())
    with _manager_lock:
        if key not in _managers:
            _managers[key] = TaskManager(settings)
        return _managers[key]
