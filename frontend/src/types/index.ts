// =============================================================================
// Public types for the ScopeGraph frontend.
//
// Conventions
//  - `interface` for object shapes that other code spreads into / extends.
//  - `type` for unions and aliases.
//  - All snake_case fields mirror the backend Pydantic schema names so JSON
//    coming off /api/* can be assigned without translation.
// =============================================================================

// -----------------------------------------------------------------------------
// Discriminated unions
// -----------------------------------------------------------------------------

/** Role of a chat-message author. */
export type ChatRole = 'user' | 'assistant' | 'system'

/** Lifecycle of a single chat message on the client side. */
export type ChatMessageStatus = 'pending' | 'streaming' | 'complete' | 'error'

/** Role attached to a JWT-authenticated user. */
export type UserRole = 'user' | 'admin'

/** Member tier — drives perks and visible feature set. */
/** Discriminator for a Tier-2 confirmation card. */
export type ConfirmationStatus =
  | 'pending'
  | 'confirmed'
  | 'cancelled'
  | 'expired'

/** Backend → frontend SSE event names emitted by /api/chat/stream. */
export type StreamEventKind =
  | 'session'
  | 'message'
  | 'thinking'
  | 'status'
  | 'token'
  | 'done'
  | 'error'
  | 'confirmation'
  | 'escalation'

// -----------------------------------------------------------------------------
// Chat
// -----------------------------------------------------------------------------

/** A single chat message rendered in the conversation pane. */
export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  /** ISO-8601 timestamp; convenient for sort and display. */
  timestamp?: string
  /** Lifecycle marker — drives spinners, error styling, etc. */
  status?: ChatMessageStatus
  /** When set, the bubble shows a Tier-2 confirmation card instead of plain text. */
  confirmation?: ConfirmationPayload
  /** Convenience flag the chat store flips while a stream is in flight. */
  isStreaming?: boolean
  /** Set when the assistant decides to hand off to a human agent. */
  escalation?: EscalationInfo
}

/** Backwards-compatible alias — old call sites still import `Message`. */
export type Message = ChatMessage

/** Tier-2 operation requiring user confirmation before execution. */
export interface ConfirmationPayload {
  operationId: string
  summary: string
  details: Record<string, string>
  /** ISO-8601 expiry timestamp — past this, the card is invalid. */
  expiresAt: string
  status: ConfirmationStatus
}

/** Escalation metadata when a conversation is handed off to a human. */
export interface EscalationInfo {
  reason: string
  agentId?: string
  queuePosition?: number
}

/** Response body of `POST /api/chat`. */
export interface ChatResponse {
  session_id: string
  reply: string
  intent?: string
  /** Convenience for clients — the backend may emit either of these. */
  sources?: ChatSource[]
  need_confirmation?: boolean
  confirmation_summary?: string
  escalation?: boolean
}

/** A document / row referenced by the assistant when answering. */
export interface ChatSource {
  title: string
  url?: string
  /** Free-form snippet the UI can render under the link. */
  snippet?: string
}

/** SSE event payload — backend uses `event` key, `type` kept for compatibility. */
export interface StreamEvent {
  event?: StreamEventKind
  type?: StreamEventKind
  data: string
}

// -----------------------------------------------------------------------------
// Auth / user
// -----------------------------------------------------------------------------

/** Response body of `POST /api/auth/login`. */
export interface LoginResponse {
  access_token: string
  token_type: string
  user_id: string
  username: string
  nickname?: string
  avatar_url?: string
  role: UserRole
  accessible_enterprises: string[]
}

/**
 * Canonical view of the authenticated user as carried in the auth store and
 * referenced by `LoginView`, `ProfileDrawer`, and the navigation bar.
 */
export interface User {
  user_id: string
  username: string
  nickname?: string
  avatar_url?: string
  bio?: string
  phone?: string
  role: UserRole
  accessible_enterprises: string[]
}

/**
 * Full profile returned by `GET /api/profile`. Adds bookkeeping fields the
 * dashboard cares about; structurally a strict superset of {@link User}.
 */
export interface UserProfile extends User {
}

// -----------------------------------------------------------------------------
// Data — enterprise / indicator / observation
// -----------------------------------------------------------------------------

/** One enterprise (company) returned by `/api/data/enterprises`. */
export interface EnterpriseRow {
  customer_id: string
  name: string
  city?: string
  address?: string
  phone?: string
}

/** One indicator (metric) returned by `/api/data/indicators`. */
export interface IndicatorRow {
  indicator_id: number
  name: string
  category?: string
  unit?: string
}

/** One enterprise × year × indicator data point, flat-row style. */
export interface Observation {
  order_id: number
  customer_id: string
  enterprise: string
  indicator: string
  indicator_id: number
  category?: string
  year: number
  value: number
  unit?: string
  source?: string
}

/** Backwards-compatible alias — DataView still imports the old name. */
export type ObservationRow = Observation

/**
 * One row of the dashboard's enterprise league table — Scope 1/2 emissions
 * for the latest closed year (2024).
 */
export interface EnterpriseSummary {
  id: string
  name: string
  industry?: string
  scope1_2024: number
  scope2_2024: number
  total_2024: number
  unit?: string
}
