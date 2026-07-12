"""CRUD пресетов. Правка применяется только к будущим job (старые заморожены)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Preset
from ..schemas import PresetCreate, PresetOut, PresetUpdate

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("", response_model=list[PresetOut])
def list_presets(db: Session = Depends(get_db)):
    return db.execute(select(Preset).order_by(Preset.id)).scalars().all()


@router.get("/{preset_id}", response_model=PresetOut)
def get_preset(preset_id: int, db: Session = Depends(get_db)):
    p = db.get(Preset, preset_id)
    if not p:
        raise HTTPException(404, "preset not found")
    return p


@router.post("", response_model=PresetOut, status_code=201)
def create_preset(data: PresetCreate, db: Session = Depends(get_db)):
    p = Preset(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: int, data: PresetUpdate, db: Session = Depends(get_db)):
    p = db.get(Preset, preset_id)
    if not p:
        raise HTTPException(404, "preset not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p
