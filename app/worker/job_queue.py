from functools import lru_cache
from typing import Optional

from redis import Redis
from rq import Callback, Queue, Retry

from app.core.config import settings

QUEUE_NAME = "analyses"
FAILED_JOB_TTL = 300
# Uma nova tentativa, 10 s depois. Pior caso de uma analise:
#   2 tentativas x (timeout do Gemini x modelos) + 10 s = 2 x (40 s x 2) + 10 = 170 s
# O app espera 3 min (e pode continuar esperando pelo mesmo id). Antes eram 4
# tentativas com 15/60/180 s de intervalo e 90 s por chamada: mais de 6 min, e o
# app desistia em 2 min - o resultado chegava depois e era jogado fora.
RETRY = Retry(max=1, interval=[10])


def job_timeout_seconds() -> int:
    """Tempo maximo de um job: todos os modelos da lista estourando o timeout."""
    return (settings.gemini_timeout_ms // 1000) * len(settings.gemini_models) + 20


def worst_case_seconds() -> int:
    """Do envio ao FAILED, no pior caso (o app usa isso para decidir quanto esperar)."""
    tentativas = 1 + RETRY.max
    return tentativas * (job_timeout_seconds() - 20) + sum(RETRY.intervals)


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())


def enqueue_analysis(
    analysis_id: str, image: bytes, mime_type: str, plate_type: Optional[str] = None
) -> None:
    get_queue().enqueue_call(
        "app.worker.tasks.process_analysis",
        args=(analysis_id, image, mime_type, plate_type),
        job_id=analysis_id,
        timeout=job_timeout_seconds(),
        result_ttl=0,
        failure_ttl=FAILED_JOB_TTL,
        retry=RETRY,
        on_failure=Callback("app.worker.result_store.on_job_failure"),
    )
