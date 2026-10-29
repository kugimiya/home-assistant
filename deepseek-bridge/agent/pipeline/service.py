"""Job queue and worker thread lifecycle."""

from __future__ import annotations

import queue
import threading
import traceback

from agent.pipeline.config import (
    jobs_retention_days,
    max_concurrent_jobs,
    pipeline_enabled,
    use_stub_worker,
)
from agent.pipeline.models import JobStatus
from agent.pipeline.store import get_job_store


def _log(msg: str) -> None:
    print(msg.replace("\n", " "), flush=True)


class JobService:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._sem = threading.Semaphore(max_concurrent_jobs())
        self._started = False
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def ensure_started(self) -> None:
        if not pipeline_enabled():
            return
        with self._lock:
            if self._started:
                return
            store = get_job_store()
            n = store.requeue_running_jobs()
            if n:
                _log(f"pipeline requeued running jobs={n}")
            pruned = store.prune_old_jobs(jobs_retention_days())
            if pruned:
                _log(f"pipeline pruned rows={pruned}")
            workers = max_concurrent_jobs()
            for i in range(workers):
                thread = threading.Thread(
                    target=self._worker_loop,
                    name=f"pipeline-worker-{i}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            self._started = True
            _log(f"pipeline service started workers={workers}")

    def enqueue(self, job_id: str) -> None:
        if not pipeline_enabled():
            return
        self.ensure_started()
        self._queue.put(job_id)
        _log(f"job {job_id[-8:]} enqueued")

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._sem.acquire()
                try:
                    self._run_one(job_id)
                finally:
                    self._sem.release()
            except Exception:
                _log("pipeline worker error " + traceback.format_exc().splitlines()[-1])
            finally:
                self._queue.task_done()

    def _run_one(self, job_id: str) -> None:
        store = get_job_store()
        job = store.get_job(job_id)
        if job is None:
            return
        if job.status == JobStatus.CANCELED:
            return
        if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return
        from agent.pipeline import worker as worker_mod

        if use_stub_worker():
            worker_mod.run_job_stub(job_id)
        else:
            worker_mod.run_job(job_id)


_SERVICE: JobService | None = None


def get_job_service() -> JobService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = JobService()
    return _SERVICE
