"""Employer contact extraction (only from officially published data)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Contact, Vacancy
from .sources.base import RawVacancy


def extract_and_save(db: Session, vacancy: Vacancy, rv: RawVacancy) -> Contact | None:
    if not (rv.contact_name or rv.contact_phone or rv.contact_email):
        return None
    existing = db.query(Contact).filter(Contact.vacancy_id == vacancy.id).first()
    if existing:
        return existing
    contact = Contact(
        vacancy_id=vacancy.id,
        name=rv.contact_name or "",
        phone=rv.contact_phone or "",
        email=rv.contact_email or "",
    )
    db.add(contact)
    db.flush()
    return contact
