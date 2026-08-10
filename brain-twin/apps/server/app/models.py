"""SQLAlchemy ORM モデル。テーブル定義そのものは app/db_schema.sql が正であり
(FTS5仮想テーブル・トリガーはORMで表現できないため)、このモジュールは
db_schema.sqlに実際に存在するテーブルへ`extend_existing`的にマッピングするだけの薄い層。
列定義はdb_schema.sqlと一致させること(片方だけ変更しない)。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    raw_text: Mapped[str] = mapped_column(nullable=False)
    input_type: Mapped[str] = mapped_column(String, nullable=False, default="text")
    captured_at: Mapped[datetime] = mapped_column(nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    sync_status: Mapped[str] = mapped_column(String, nullable=False, default="synced")
    processing_status: Mapped[str] = mapped_column(String, nullable=False, default="not_started")
    source_device: Mapped[str | None] = mapped_column(String, nullable=True)
    client_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Thought(Base):
    __tablename__ = "thoughts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    capture_id: Mapped[str] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    summary: Mapped[str | None] = mapped_column(nullable=True)
    types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    action_intent: Mapped[float | None] = mapped_column(nullable=True)
    resurface_need: Mapped[float | None] = mapped_column(nullable=True)
    emotional_weight: Mapped[float | None] = mapped_column(nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String, nullable=True)
    user_notes: Mapped[str | None] = mapped_column(nullable=True)
    certainty: Mapped[float | None] = mapped_column(nullable=True)
    importance: Mapped[float | None] = mapped_column(nullable=True)
    urgency: Mapped[float | None] = mapped_column(nullable=True)
    mental_load: Mapped[float | None] = mapped_column(nullable=True)
    forget_safely_score: Mapped[float | None] = mapped_column(nullable=True)
    possible_dates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    project_names_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    people_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    places_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    ai_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    analysis_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    canonical_name: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class ThoughtEntity(Base):
    __tablename__ = "thought_entities"

    thought_id: Mapped[str] = mapped_column(ForeignKey("thoughts.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="ai")


class ThoughtLink(Base):
    __tablename__ = "thought_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_thought_id: Mapped[str] = mapped_column(ForeignKey("thoughts.id", ondelete="CASCADE"), nullable=False)
    target_thought_id: Mapped[str] = mapped_column(ForeignKey("thoughts.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ThoughtEmbedding(Base):
    __tablename__ = "thought_embeddings"

    thought_id: Mapped[str] = mapped_column(ForeignKey("thoughts.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    dim: Mapped[int] = mapped_column(nullable=False)
    vector_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thought_id: Mapped[str | None] = mapped_column(ForeignKey("thoughts.id", ondelete="CASCADE"), nullable=True)
    capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_value: Mapped[str | None] = mapped_column(nullable=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    capture_id: Mapped[str] = mapped_column(ForeignKey("captures.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


class SyncDevice(Base):
    __tablename__ = "sync_devices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    device_name: Mapped[str] = mapped_column(nullable=False)
    device_token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
