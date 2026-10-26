from fastapi import APIRouter, Query

from app.schemas import FoodOut
from app.services import taco_table

router = APIRouter(prefix="/foods", tags=["foods"])


@router.get(
    "",
    response_model=list[FoodOut],
    summary="Search foods in the TACO table (to correct an item)",
)
def search_foods(
    search: str = Query(min_length=2),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[FoodOut]:
    return [
        FoodOut(id=f.id, name=f.name, category=f.category)
        for f in taco_table.search_foods(search, limit)
    ]
