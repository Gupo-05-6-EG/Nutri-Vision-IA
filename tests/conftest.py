import io
import os
import random
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="nutrivision-test-"))
os.environ["NUTRIVISION_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["NUTRIVISION_TACO_CSV"] = str(Path(__file__).parent / "fixtures" / "taco_sample.csv")
os.environ["NUTRIVISION_GEMINI_API_KEY"] = "test-key"

from PIL import Image

from app.core.database import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


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
