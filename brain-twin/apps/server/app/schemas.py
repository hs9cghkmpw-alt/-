"""API入出力のPydanticスキーマ。packages/shared-types/src/index.ts と構造を対応させる
(フィールド名はPython慣例のsnake_caseのまま公開し、フロント側でキャメルケースへ変換する
運用。variantを増やす場合は両方を更新すること)。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- 思考マップ・enum系の型(packages/shared-types/src/index.ts と対応) ----

ThoughtType = Literal[
    "thought",
    "action_candidate",
    "idea",
    "emotion",
    "body_state",
    "memory",
    "concern",
    "question",
    "observation",
    "appointment",
    "shopping",
    "project",
    "family",
    "work",
    "uncertain_deadline",
    "unfinished_thought",
    "background_noise",
]

EntityType = Literal["emotion", "idea", "state", "topic", "person", "place", "project", "organization", "other"]
Sentiment = Literal["positive", "neutral", "negative", "idea_goal"]


# ---- captures ----


class CaptureCreate(BaseModel):
    client_id: str
    raw_text: str = Field(min_length=1)
    input_type: Literal["text", "voice_dictation"] = "text"
    captured_at: str
    source_device: str | None = None
    client_version: str | None = None


class CaptureOut(BaseModel):
    id: str
    client_id: str
    raw_text: str
    input_type: str
    captured_at: str | None
    received_at: str | None
    sync_status: str
    processing_status: str
    source_device: str | None = None
    client_version: str | None = None
    created_at: str | None
    updated_at: str | None
    deleted_at: str | None = None


class CaptureListResponse(BaseModel):
    items: list[CaptureOut]


# ---- thoughts ----


class ThoughtEntityOut(BaseModel):
    name: str
    entity_type: str
    confidence: float | None = None


class PossibleDateOut(BaseModel):
    raw_text: str
    resolved_date: str | None = None
    precision: str = "unknown"


class ThoughtOut(BaseModel):
    id: str
    capture_id: str
    content: str
    summary: str | None = None
    types: list[str] = Field(default_factory=list)
    action_intent: float | None = None
    resurface_need: float | None = None
    emotional_weight: float | None = None
    sentiment: str | None = None
    user_notes: str | None = None
    certainty: float | None = None
    importance: float | None = None
    urgency: float | None = None
    mental_load: float | None = None
    forget_safely_score: float | None = None
    entities: list[ThoughtEntityOut] = Field(default_factory=list)
    possible_dates: list[dict[str, Any]] = Field(default_factory=list)
    project_names: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    ai_model: str | None = None
    ai_prompt_version: str | None = None
    analysis_version: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None
    done_at: str | None = None


class ThoughtListResponse(BaseModel):
    items: list[ThoughtOut]


class ThoughtLinkOut(BaseModel):
    id: str
    source_thought_id: str
    target_thought_id: str
    relation_type: str
    score: float | None = None
    reason: str | None = None
    created_by: str
    created_at: str | None = None


class ThoughtLinksResponse(BaseModel):
    items: list[ThoughtLinkOut]


# ---- feedback ----

FeedbackEventType = Literal[
    "viewed",
    "opened",
    "closed",
    "searched",
    "snoozed",
    "marked_not_this",
    "marked_important",
    "marked_just_a_thought",
    "marked_want_to_act",
    "marked_ok_to_forget",
    "marked_related",
    "marked_not_related",
    "re_entered",
    "marked_done",
    "checked_relation",
]


class FeedbackCreate(BaseModel):
    event_type: FeedbackEventType
    event_value: str | None = None
    context_json: dict[str, Any] | None = None


class FeedbackEventOut(BaseModel):
    id: str
    thought_id: str | None = None
    capture_id: str | None = None
    event_type: str
    event_value: str | None = None
    created_at: str | None = None


# ---- search ----


class SearchThoughtHit(BaseModel):
    thought: ThoughtOut
    capture_id: str
    snippet: str | None = None


class SearchResponse(BaseModel):
    query: str
    thoughts: list[SearchThoughtHit] = Field(default_factory=list)
    captures: list[CaptureOut] = Field(default_factory=list)


# ---- sync (オフラインキュー再送用の一括API) ----


class SyncCaptureItem(BaseModel):
    client_id: str
    raw_text: str = Field(min_length=1)
    input_type: Literal["text", "voice_dictation"] = "text"
    captured_at: str
    source_device: str | None = None
    client_version: str | None = None


class SyncCapturesRequest(BaseModel):
    captures: list[SyncCaptureItem] = Field(default_factory=list, max_length=200)


class SyncCaptureResult(BaseModel):
    client_id: str
    status: Literal["created", "already_exists"]
    capture: CaptureOut


class SyncCapturesResponse(BaseModel):
    results: list[SyncCaptureResult]


class SyncChangesResponse(BaseModel):
    server_time: str
    captures: list[CaptureOut]
    thoughts: list[ThoughtOut]
    next_cursor: str | None = None


# ---- pairing ----


class PairingStartResponse(BaseModel):
    code: str
    expires_at: str
    expires_in_seconds: int


class PairingCompleteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(min_length=1, max_length=200)


class PairingCompleteResponse(BaseModel):
    device_id: str
    device_token: str


# ---- jobs / processing ----


class JobOut(BaseModel):
    id: str
    capture_id: str
    job_type: str
    status: str
    attempt_count: int
    last_error: str | None = None
    scheduled_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class JobListResponse(BaseModel):
    items: list[JobOut]


class ProcessingRetryResponse(BaseModel):
    accepted: bool
    capture_id: str
    job_id: str


# ---- backup / export ----


class BackupResponse(BaseModel):
    ok: bool
    path: str | None = None
    message: str
    deleted_old: list[str] = Field(default_factory=list)


class ExportResponse(BaseModel):
    ok: bool
    path: str | None = None
    message: str
    thought_count: int = 0
    capture_count: int = 0


# ---- settings ----


class SettingsOut(BaseModel):
    ollama_base_url: str
    ollama_model: str
    ollama_embedding_model: str
    backup_retention_generations: int
    overrides: dict[str, Any] = Field(default_factory=dict)


class SettingUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any


# ---- health / status ----


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app_name: str
    version: str


class StatusResponse(BaseModel):
    ollama_available: bool | Literal["unknown"]
    ollama_base_url: str
    pending_sync_count: int
    pending_processing_count: int
    failed_processing_count: int
