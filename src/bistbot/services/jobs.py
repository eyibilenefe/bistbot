from __future__ import annotations

from datetime import datetime, UTC
from threading import Lock, Thread
from typing import Callable

from bistbot.domain.enums import JobName
from bistbot.domain.models import JobRun


class JobService:
    def __init__(self) -> None:
        self.job_runs: list[JobRun] = []
        self._refresh_jobs: dict[str, dict[str, object]] = {}
        self._refresh_lock = Lock()
        self._refresh_sequence = 0

    def run(self, job_name: str) -> JobRun:
        if job_name not in {member.value for member in JobName}:
            raise ValueError(f"Unsupported job: {job_name}")

        started_at = datetime.now(UTC)
        completed_at = datetime.now(UTC)
        run = JobRun(
            name=job_name,
            started_at=started_at,
            completed_at=completed_at,
            status="completed",
            details={"mode": "manual_trigger_stub"},
        )
        self.job_runs.append(run)
        return run

    def start_refresh(
        self,
        refresh_fn: Callable[[Callable[[int, str], None]], dict[str, object]],
    ) -> dict[str, object]:
        with self._refresh_lock:
            existing = next(
                (
                    dict(job)
                    for job in self._refresh_jobs.values()
                    if str(job["status"]) in {"queued", "running"}
                ),
                None,
            )
            if existing is not None:
                return existing

            self._refresh_sequence += 1
            job_id = f"refresh-{self._refresh_sequence}"
            job = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "message": "Veri guncelleme siraya alindi.",
                "result": None,
                "error": None,
                "started_at": datetime.now(UTC).isoformat(),
                "completed_at": None,
            }
            self._refresh_jobs[job_id] = job

        def update_progress(percent: int, message: str) -> None:
            with self._refresh_lock:
                current = self._refresh_jobs.get(job_id)
                if current is None:
                    return
                current["status"] = "running"
                current["progress"] = max(0, min(100, int(percent)))
                current["message"] = message

        def worker() -> None:
            try:
                result = refresh_fn(update_progress)
            except Exception as exc:
                with self._refresh_lock:
                    current = self._refresh_jobs[job_id]
                    current["status"] = "failed"
                    current["error"] = str(exc)
                    current["message"] = "Veri guncelleme basarisiz oldu."
                    current["completed_at"] = datetime.now(UTC).isoformat()
                return

            with self._refresh_lock:
                current = self._refresh_jobs[job_id]
                current["status"] = "completed"
                current["progress"] = 100
                current["message"] = "Veri guncelleme tamamlandi."
                current["result"] = result
                current["completed_at"] = datetime.now(UTC).isoformat()

        Thread(target=worker, daemon=True).start()
        return dict(job)

    def get_refresh_status(self, job_id: str) -> dict[str, object]:
        with self._refresh_lock:
            job = self._refresh_jobs.get(job_id)
            if job is None:
                raise ValueError(f"Unknown refresh job: {job_id}")
            return dict(job)
