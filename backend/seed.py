"""Сид одного тестового пресета. Идемпотентно (по имени)."""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Preset

TEST_PRESET = dict(
    name="reels",  # ключевое слово команды в Telegram
    tool=settings.TOOL,  # по умолчанию stub
    format="9:16",
    voice=None,
    subtitle_style={"enabled": True, "style": "block", "color": "white", "position": "bottom", "fontsize": 44},
    prompt="Собери вертикальный ролик: хук в первые 3 сек, польза в теле, призыв в конце.",
    length=15,
    extra={},
)


def main() -> None:
    with SessionLocal() as db:
        exists = db.execute(select(Preset).where(Preset.name == TEST_PRESET["name"])).scalar_one_or_none()
        if exists:
            print(f"preset '{TEST_PRESET['name']}' уже есть (id={exists.id})")
            return
        p = Preset(**TEST_PRESET)
        db.add(p)
        db.commit()
        db.refresh(p)
        print(f"seeded preset '{p.name}' id={p.id} tool={p.tool}")


if __name__ == "__main__":
    main()
