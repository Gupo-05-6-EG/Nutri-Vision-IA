from functools import lru_cache

from redis import Redis
from rq import Queue, Retry

from app.core.config import settings

QUEUE_NAME = "analyses"
SEVEN_DAYS = 7 * 24 * 3600


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())


def enqueue_analysis(analysis_id: str, image: bytes, mime_type: str) -> None:
    get_queue().enqueue_call(
        "app.worker.tasks.process_analysis",
        args=(analysis_id, image, mime_type),
        job_id=analysis_id,
        timeout=120,
        result_ttl=0,
        failure_ttl=SEVEN_DAYS,
        retry=Retry(max=3, interval=[15, 60, 180]),
    )
