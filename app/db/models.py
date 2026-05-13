"""SQLAlchemy models for documents and chunks."""
import uuid
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class GoogleDriveChannelState(Base):
    """Last Google Drive push channel (single row id=1). Used to verify notifications."""

    __tablename__ = "google_drive_channel_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expiration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    """Document entity for ingested content."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_tenant_source", "tenant_id", "source_type", "source_id", unique=True),
    )


class Chunk(Base):
    """Chunk entity with vector embedding."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(384), nullable=True)  # all-MiniLM-L6-v2 dim
    doc_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="chunks")

    # Vector index created separately after data load (ivfflat needs rows)
