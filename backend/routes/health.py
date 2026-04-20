from fastapi import APIRouter, Depends
from backend.db.pool import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db=Depends(get_db)):
    db.execute("SELECT 1")
    return {"status": "ok"}
