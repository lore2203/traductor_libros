"""Caché de traducciones persistente en SQLite."""
from sqlalchemy.orm import Session

from app.db.models import TranslationCache


class SqlCache:
    def __init__(self, session: Session):
        self.s = session

    def get(self, key: str) -> str | None:
        row = self.s.get(TranslationCache, key)
        return row.translation if row else None

    def set(self, key: str, value: str, model: str) -> None:
        row = self.s.get(TranslationCache, key)
        if row:
            row.translation = value
        else:
            self.s.add(TranslationCache(key=key, translation=value, model=model))
        self.s.commit()
