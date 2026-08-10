/**
 * Brain Twin 共有型定義
 * ------------------------------------------------------------
 * apps/web (フロントエンド) が直接importして使う「正」の型。
 * apps/server 側は Pydantic (app/schemas.py) が同じ形を定義している
 * (Python/TypeScript間でパッケージを共有する構成を取っていないため、
 *  構造は手動で同期させる。variantを増やす際は両方を更新すること)。
 *
 * 数値属性 (action_intent 等) はすべて「確定事実ではなく推定値」。
 * null は「不明」を意味し、0 とは区別する。
 */

export type ThoughtType =
  | "thought"
  | "action_candidate"
  | "idea"
  | "emotion"
  | "body_state"
  | "memory"
  | "concern"
  | "question"
  | "observation"
  | "appointment"
  | "shopping"
  | "project"
  | "family"
  | "work"
  | "uncertain_deadline"
  | "unfinished_thought"
  | "background_noise";

export type EntityType = "topic" | "person" | "place" | "project" | "organization" | "other";

/** 思考マップの色分け用。emotional_weight(強さ)とは別の「向き」。診断ではなく表示上の分類。 */
export type Sentiment = "positive" | "neutral" | "negative" | "idea_goal";

export type DatePrecision = "day" | "week" | "month" | "unknown";

export type SyncStatus =
  | "local_only"
  | "queued"
  | "syncing"
  | "synced"
  | "sync_failed";

export type ProcessingStatus =
  | "not_started"
  | "queued"
  | "processing"
  | "done"
  | "failed"
  | "unavailable";

export type RelationType =
  | "same_project"
  | "same_person"
  | "same_topic"
  | "semantic_similarity"
  | "temporal_relation"
  | "caused_by"
  | "follow_up"
  | "user_confirmed";

export type FeedbackEventType =
  | "viewed"
  | "opened"
  | "closed"
  | "searched"
  | "snoozed"
  | "marked_not_this"
  | "marked_important"
  | "marked_just_a_thought"
  | "marked_want_to_act"
  | "marked_ok_to_forget"
  | "marked_related"
  | "marked_not_related"
  | "re_entered"
  | "marked_done"
  | "checked_relation";

/** ローカル(IndexedDB)に保存される、預けた生の入力そのもの。 */
export interface CaptureRecord {
  /** クライアント発行UUID。冪等な同期のキーになる。 */
  clientId: string;
  /** サーバー確定後に付与されるID。 */
  serverId?: string;
  rawText: string;
  inputType: "text" | "voice_dictation";
  capturedAt: string; // ISO8601, ローカル生成時刻
  receivedAt?: string; // サーバー受領時刻
  syncStatus: SyncStatus;
  processingStatus: ProcessingStatus;
  sourceDevice: string;
  clientVersion: string;
  deletedAt?: string | null;
  updatedAt: string;
  /** 保存/送信の失敗回数。UIでの静かなリトライ判断に使う。 */
  syncAttemptCount: number;
  lastSyncError?: string | null;
}

export interface ThoughtEntity {
  name: string;
  entityType: EntityType;
  confidence?: number | null;
}

export interface PossibleDate {
  rawText: string;
  resolvedDate?: string | null; // YYYY-MM-DD
  precision: DatePrecision;
}

export interface ThoughtRecord {
  id: string;
  captureId: string;
  content: string;
  summary?: string | null;
  types: ThoughtType[];
  actionIntent?: number | null;
  resurfaceNeed?: number | null;
  emotionalWeight?: number | null;
  sentiment?: Sentiment | null;
  userNotes?: string | null;
  certainty?: number | null;
  importance?: number | null;
  urgency?: number | null;
  mentalLoad?: number | null;
  forgetSafelyScore?: number | null;
  entities: ThoughtEntity[];
  possibleDates: PossibleDate[];
  projectNames: string[];
  people: string[];
  places: string[];
  aiModel?: string | null;
  aiPromptVersion?: string | null;
  analysisVersion?: string | null;
  createdAt: string;
  updatedAt: string;
  deletedAt?: string | null;
}

export interface ThoughtLink {
  id: string;
  sourceThoughtId: string;
  targetThoughtId: string;
  relationType: RelationType;
  score?: number | null;
  reason?: string | null;
  createdBy: "ai" | "user" | "rule";
  createdAt: string;
}

export interface FeedbackEvent {
  id?: string;
  thoughtId?: string | null;
  captureId?: string | null;
  eventType: FeedbackEventType;
  eventValue?: string | null;
  contextJson?: Record<string, unknown> | null;
  createdAt: string;
}

/** 表側で見せる、静かな状態表示のための集約状態。 */
export interface ConnectionState {
  pcReachable: boolean;
  ollamaAvailable: boolean | "unknown";
  pendingSyncCount: number;
  pendingProcessingCount: number;
  lastSyncedAt?: string | null;
}

// ---- Ollama へ渡す/から返す JSON の型 (packages/shared-types/src/thought_split.schema.json と対応) ----

export interface ThoughtSplitItem {
  content: string;
  summary?: string | null;
  types: ThoughtType[];
  action_intent?: number | null;
  resurface_need?: number | null;
  emotional_weight?: number | null;
  sentiment?: Sentiment | null;
  certainty?: number | null;
  importance?: number | null;
  urgency?: number | null;
  mental_load?: number | null;
  forget_safely_score?: number | null;
  entities?: { name: string; entity_type: EntityType }[];
  possible_dates?: { raw_text: string; resolved_date?: string | null; precision: DatePrecision }[];
  project_names?: string[];
  people?: string[];
  places?: string[];
}

export interface ThoughtSplitResult {
  thoughts: ThoughtSplitItem[];
}

// ---- 思考マップ(固定カテゴリではなく動的ラベルによる可視化) ----

export interface ThoughtMapNode {
  id: string;
  label: string;
  entityType: EntityType;
  thoughtCount: number;
  dominantSentiment?: Sentiment | null;
  sentimentBreakdown: Partial<Record<Sentiment, number>>;
  latestThoughtAt?: string | null;
}

export interface ThoughtMapEdge {
  source: string;
  target: string;
  weight: number;
}

export interface ThoughtMapData {
  nodes: ThoughtMapNode[];
  edges: ThoughtMapEdge[];
  generatedAt: string;
}

export interface LabelThoughts {
  label: ThoughtMapNode;
  items: ThoughtRecord[];
  nextCursor?: string | null;
}
