import json
from typing import Optional

from app.core.config import settings
from app.services.analysis_result import AnalysisStatus
from app.worker import job_queue

KEY_PREFIX = "nutrivision:analysis:"


def _key(analysis_id: str) -> str:
    return f"{KEY_PREFIX}{analysis_id}"


def save(analysis: dict) -> None:
    job_queue.get_redis().set(_key(analysis["id"]), json.dumps(analysis), ex=settings.result_ttl_seconds)


def get(analysis_id: str) -> Optional[dict]:
    raw = job_queue.get_redis().get(_key(analysis_id))
    return None if raw is None else json.loads(raw)


def update(analysis_id: str, **fields) -> None:
    analysis = get(analysis_id) or {"id": analysis_id}
    analysis.update(fields)
    save(analysis)


def on_job_failure(job, connection, exc_type, exc_value, traceback) -> None:
    if job.retries_left:
        return
    update(
        job.id,
        status=AnalysisStatus.FAILED.value,
        error=f"{getattr(exc_type, '__name__', exc_type)}: {exc_value}",
    )
