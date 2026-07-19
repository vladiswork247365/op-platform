"""Small helpers for the audit log and error log."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog, ErrorLog


def audit(db: Session, action: str, detail: str = "", vacancy_id: int | None = None) -> None:
    db.add(AuditLog(action=action, detail=detail[:2000], vacancy_id=vacancy_id))
    db.flush()


def log_error(
    db: Session,
    component: str,
    message: str,
    kind: str = "error",
    permanent: bool = False,
) -> None:
    db.add(
        ErrorLog(
            component=component,
            kind=kind,
            message=message[:2000],
            permanent=permanent,
        )
    )
    db.flush()
