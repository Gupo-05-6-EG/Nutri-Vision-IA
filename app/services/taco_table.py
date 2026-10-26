import csv
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from app.core.config import settings


class TacoTableUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class TacoFood:
    id: int
    name: str
    category: str = ""


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def _load_table() -> dict:
    try:
        with open(settings.taco_csv, encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file, delimiter=";"))
    except OSError as exc:
        raise TacoTableUnavailableError(f"TACO table not found at {settings.taco_csv}") from exc

    table = {}
    for row in rows:
        food = TacoFood(
            id=int(row["id"]),
            name=row["name"].strip(),
            category=(row.get("category") or "").strip(),
        )
        table[food.id] = food
    if not table:
        raise TacoTableUnavailableError(f"TACO table is empty at {settings.taco_csv}")
    return table


def get_food(taco_id: int) -> Optional[TacoFood]:
    return _load_table().get(taco_id)


def format_for_prompt() -> str:
    return "\n".join(f"{f.id}|{f.name}" for f in _load_table().values())


def search_foods(text: str, limit: int = 20) -> list:
    terms = _fold(text).split()
    matches = [f for f in _load_table().values() if all(t in _fold(f.name) for t in terms)]
    return matches[:limit]
