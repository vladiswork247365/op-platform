"""WhatsApp module — NOT configured in this build.

The system is wired end-to-end (contact extraction, message template, statuses,
idempotency) but automatic sending is intentionally disabled. When a contact
phone is available the prepared message is stored with status NOT_CONFIGURED so
it is visible in the panel; a real provider adapter can be dropped in later
without touching the pipeline.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Contact, Vacancy, WhatsAppMessage, WhatsAppStatus


def prepare(db: Session, vacancy: Vacancy, contact: Contact | None, template: str) -> str:
    """Store the prepared message + resulting status. Never sends."""
    key = f"wa:{vacancy.id}"
    existing = (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.idempotency_key == key)
        .first()
    )
    if existing:
        return existing.status

    phone = (contact.phone if contact else "") or ""
    if not phone:
        status = WhatsAppStatus.WHATSAPP_NOT_AVAILABLE.value
        body = ""
    else:
        status = WhatsAppStatus.NOT_CONFIGURED.value
        body = (template or "").strip()

    db.add(
        WhatsAppMessage(
            vacancy_id=vacancy.id,
            phone=phone,
            body=body,
            status=status,
            idempotency_key=key,
        )
    )
    db.flush()
    return status


def healthcheck() -> tuple[bool, str]:
    # Not an error state — simply not configured.
    return True, "not configured"
