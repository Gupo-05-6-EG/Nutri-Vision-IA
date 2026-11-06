import io
import os
import random
from pathlib import Path

import pytest

os.environ["NUTRIVISION_TACO_CSV"] = str(Path(__file__).parent / "fixtures" / "taco_sample.csv")
os.environ["NUTRIVISION_GEMINI_API_KEY"] = "test-key"

import fakeredis
from PIL import Image
from rq import Queue

from app.worker import job_queue


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    connection = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(job_queue, "get_redis", lambda: connection)
    monkeypatch.setattr(
        job_queue,
        "get_queue",
        lambda: Queue(job_queue.QUEUE_NAME, connection=connection, is_async=False),
    )
    return connection


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def sharp_photo() -> bytes:
    rnd = random.Random(42)
    image = Image.new("L", (256, 256))
    image.putdata([rnd.randint(60, 200) for _ in range(256 * 256)])
    return _png(image.convert("RGB"))


@pytest.fixture
def blurry_photo() -> bytes:
    return _png(Image.new("RGB", (256, 256), (128, 128, 128)))
