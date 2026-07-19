"""/health endpoint — component status, last cycle, queue depth, 24h errors."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..health import ERROR, build_health
from ..scheduler import MANAGER

router = APIRouter(tags=["health"])


@router.get("/health")
def health(deep: bool = False, db: Session = Depends(get_db)) -> JSONResponse:
    report = build_health(db, scheduler=MANAGER.scheduler, deep=deep)
    code = 503 if report["status"] == ERROR else 200
    return JSONResponse(report, status_code=code)
