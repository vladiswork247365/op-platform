"""Deduplication helpers.

Two layers of protection:
  1. Exact: (source, external_id) uniqueness (enforced in DB + checked here).
  2. Content: hash of company + title + normalised description, catching the
     same job re-posted under a new id.
"""
from __future__ import annotations

import hashlib
import re

from sqlalchemy.orm import Session

from .models import Vacancy
from .sources.base import RawVacancy

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def content_hash(rv: RawVacancy) -> str:
    basis = "|".join(
        [normalize(rv.company), normalize(rv.title), normalize(rv.description)]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_known(db: Session, source: str, external_id: str, chash: str) -> bool:
    """True if this vacancy was seen before (by id or by content hash)."""
    by_id = (
        db.query(Vacancy.id)
        .filter(Vacancy.source == source, Vacancy.external_id == external_id)
        .first()
    )
    if by_id is not None:
        return True
    by_hash = db.query(Vacancy.id).filter(Vacancy.content_hash == chash).first()
    return by_hash is not None
