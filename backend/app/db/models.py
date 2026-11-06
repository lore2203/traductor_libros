"""Modelo de datos. Los PDF viven en disco; aquí solo rutas, hashes y metadatos."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(Text)
    title_es: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    jobs: Mapped[list[Job]] = relationship(back_populates="document")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    # queued | running | paused | cancelled | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # upload | analyze | protect | ocr | translate | rebuild | validate | done
    stage: Mapped[str] = mapped_column(String(16), default="upload")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_page: Mapped[int | None] = mapped_column(Integer)
    source_lang: Mapped[str] = mapped_column(String(8), default="en")
    target_lang: Mapped[str] = mapped_column(String(8), default="es")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    output_path: Mapped[str | None] = mapped_column(String(1024))
    report_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document: Mapped[Document] = relationship(back_populates="jobs")
    pages: Mapped[list[Page]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("job_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1-based
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    # blank | digital | scanned | mixed | image_only
    kind: Mapped[str] = mapped_column(String(16))
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    drawing_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)

    job: Mapped[Job] = relationship(back_populates="pages")
    segments: Mapped[list[Segment]] = relationship(back_populates="page", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), index=True)
    seg_key: Mapped[str] = mapped_column(String(32))  # p041_s03
    bbox: Mapped[list] = mapped_column(JSON)
    block_type: Mapped[str] = mapped_column(String(16), default="text")
    style: Mapped[dict] = mapped_column(JSON, default=dict)
    source_text: Mapped[str] = mapped_column(Text)
    source_html: Mapped[str] = mapped_column(Text)
    protected_text: Mapped[str | None] = mapped_column(Text)
    placeholders: Mapped[dict] = mapped_column(JSON, default=dict)
    translation: Mapped[str | None] = mapped_column(Text)
    # translate | keep | graphic | review
    action: Mapped[str] = mapped_column(String(16), default="translate")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    fit_scale: Mapped[float | None] = mapped_column(Float)
    issues: Mapped[list] = mapped_column(JSON, default=list)

    page: Mapped[Page] = relationship(back_populates="segments")


class ProtectedTerm(Base):
    __tablename__ = "protected_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(512))
    category: Mapped[str] = mapped_column(String(16), default="NAME")
    origin: Mapped[str] = mapped_column(String(16), default="manual")  # auto | manual
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))  # None = global


class GlossaryEntry(Base):
    __tablename__ = "glossary"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(512))
    target: Mapped[str] = mapped_column(String(512))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))


class TranslationCache(Base):
    __tablename__ = "translation_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    translation: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
