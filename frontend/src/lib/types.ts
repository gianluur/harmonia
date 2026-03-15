/**
 * Harmonia – TypeScript type definitions.
 *
 * Every type here mirrors a Pydantic model in backend/schemas.py.
 * Field names follow camelCase (TypeScript convention).
 * Optional Python fields (field: T | None = None) become optional here (field?: T).
 *
 * See also WS_EVENT_TYPES at the bottom for the WebSocket dispatcher map.
 */

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

/** Lifecycle states a background acquisition job can be in. */
export type JobStatusEnum =
  | "pending"
  | "downloading"
  | "tagging"
  | "confirmed"
  | "error";

/** Origin of a tagging suggestion. */
export type TagSource = "beets" | "musicbrainz" | "custom" | "manual";

/** Actions a source plugin can perform. */
export type PluginCapability = "search" | "stream" | "acquire";

/** Input modalities a plugin's search endpoint accepts. */
export type PluginSearchInput = "query" | "url";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Payload for the first-run setup endpoint that creates the admin account. */
export interface SetupRequest {
  username: string;
  password: string;
}

/** Credentials posted to the login endpoint. */
export interface LoginRequest {
  username: string;
  password: string;
}

/** Tells the frontend whether initial setup has been completed. */
export interface AuthStatus {
  configured: boolean;
}

/** JWT issued on successful authentication. */
export interface TokenResponse {
  accessToken: string;
  tokenType: string;
  expiresAt: string; // ISO 8601 datetime
}

// ---------------------------------------------------------------------------
// Jobs & Acquisition
// ---------------------------------------------------------------------------

/** Request body for POST /api/acquire – starts a new acquisition job. */
export interface AcquireRequest {
  youtubeId: string;
  titleHint?: string;
}

/** Response from POST /api/acquire containing identifiers for the new job. */
export interface AcquireResponse {
  jobId: string;
  streamToken: string;
}

/** Current state of an acquisition job, including optional progress data. */
export interface JobStatus {
  jobId: string;
  status: JobStatusEnum;
  percent?: number;
  errorMessage?: string;
  createdAt: string; // ISO 8601 datetime
}

/** Internal signed token scoped to a single job for stream authentication. */
export interface StreamToken {
  jobId: string;
  expiresAt: string; // ISO 8601 datetime
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

/** Parameters for initiating a search; at least one of query or url is required. */
export interface SearchRequest {
  query?: string;
  url?: string;
}

/** A single candidate track returned by a source plugin during search. */
export interface SearchResult {
  id: string;
  title: string;
  artist: string;
  durationSeconds: number;
  thumbnailUrl: string;
  sourcePlugin: string;
  sourceUrl: string;
  year?: number;
}

/** Signals that a search operation has finished and provides the total result count. */
export interface SearchCompleteEvent {
  searchId: string;
  total: number;
}

// ---------------------------------------------------------------------------
// Tagging
// ---------------------------------------------------------------------------

/** Final tag values submitted by the user to be written to an audio file. */
export interface TagPayload {
  title: string;
  artist: string;
  album?: string;
  year?: number;
  trackNumber?: number;
  discNumber?: number;
  genre?: string;
  coverArtUrl?: string;
  coverArtB64?: string;
  mbRecordingId?: string;
  mbReleaseId?: string;
}

/** A tagging suggestion from an automated source, annotated with confidence. */
export interface TagCandidate extends TagPayload {
  /** Confidence score between 0.0 and 1.0. */
  confidence: number;
  source: TagSource;
}

// ---------------------------------------------------------------------------
// WebSocket Events
// ---------------------------------------------------------------------------

/** Real-time download progress pushed over the job WebSocket. */
export interface DownloadProgressEvent {
  type: "download_progress";
  percent: number;
  speed: number;
  eta: number;
}

/** Emitted when yt-dlp finishes writing the audio file to disk. */
export interface DownloadCompleteEvent {
  type: "download_complete";
  jobId: string;
  filePath: string;
}

/** Carries beets/MusicBrainz tag candidates for display in the tagging panel. */
export interface TaggingSuggestionsEvent {
  type: "tagging_suggestions";
  candidates: TagCandidate[];
}

/** Emitted once a track has been tagged, moved, and added to the Navidrome library. */
export interface LibraryReadyEvent {
  type: "library_ready";
  navidromeId: string;
  filePath: string;
}

/** Signals an acquisition job failure, distinguishing recoverable from fatal errors. */
export interface JobErrorEvent {
  type: "job_error";
  message: string;
  recoverable: boolean;
}

/** Streams a single search result to the frontend as it resolves. */
export interface SearchResultEvent {
  type: "search_result";
  result: SearchResult;
}

/**
 * Discriminated union of events emitted on the per-job WebSocket
 * (ws://<backend>/ws/<job_id>).
 */
export type JobWSEvent =
  | DownloadProgressEvent
  | DownloadCompleteEvent
  | TaggingSuggestionsEvent
  | LibraryReadyEvent
  | JobErrorEvent;

/**
 * Discriminated union of events emitted on the search WebSocket
 * (ws://<backend>/ws/search).
 */
export type SearchWSEvent = SearchResultEvent | SearchCompleteEvent;

/**
 * Full union of all WebSocket event types across both channels.
 * Prefer the narrower JobWSEvent or SearchWSEvent at call sites.
 */
export type WSEvent = JobWSEvent | SearchWSEvent;

/**
 * Mapping from WebSocket event type string to its TypeScript interface.
 * Use this const object in the WebSocket dispatcher to narrow event types.
 *
 * @example
 * function dispatch(raw: JobWSEvent) {
 *   switch (raw.type) {
 *     case JOB_WS_EVENT_TYPES.download_progress: // raw is DownloadProgressEvent
 *   }
 * }
 */
export const JOB_WS_EVENT_TYPES = {
  download_progress: "download_progress" as const,
  download_complete: "download_complete" as const,
  tagging_suggestions: "tagging_suggestions" as const,
  library_ready: "library_ready" as const,
  job_error: "job_error" as const,
} satisfies Record<JobWSEvent["type"], JobWSEvent["type"]>;

export const SEARCH_WS_EVENT_TYPES = {
  search_result: "search_result" as const,
  search_complete: "search_complete" as const,
} satisfies Record<SearchWSEvent["type"], SearchWSEvent["type"]>;

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

/** A MusicBrainz artist entity returned from the metadata proxy. */
export interface MusicBrainzArtist {
  mbid: string;
  name: string;
  disambiguation?: string;
  score: number;
}

/** A MusicBrainz release (album) associated with a recording. */
export interface MusicBrainzRelease {
  mbid: string;
  title: string;
  date?: string;
  trackCount?: number;
}

/** A MusicBrainz recording (track) with its linked releases. */
export interface MusicBrainzRecording {
  mbid: string;
  title: string;
  artistCredit?: string;
  releases: MusicBrainzRelease[];
}

/** Backend-relative URL pointing to a proxied cover art image. */
export interface CoverArtResponse {
  url: string;
  mbid: string;
}

// ---------------------------------------------------------------------------
// Custom Metadata
// ---------------------------------------------------------------------------

/** A user-defined track entry persisted in the local Custom Metadata Store. */
export interface CustomTrack {
  id: string;
  title: string;
  artist?: string;
  album?: string;
  year?: number;
  genre?: string;
  sourceQuery?: string;
  youtubeId?: string;
  createdAt: string; // ISO 8601 datetime
}

/** A tagging suggestion sourced exclusively from the local Custom Metadata Store. */
export interface CustomMetadataSuggestion {
  source: "custom";
  confidence: number;
  track: CustomTrack;
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

/** Aggregated performance counters for the search subsystem. */
export interface SearchMetrics {
  count: number;
  avgDurationMs: number;
  p95DurationMs: number;
}

/** Aggregated performance counters for the download subsystem. */
export interface DownloadMetrics {
  count: number;
  avgDurationMs: number;
  totalBytes: number;
}

/** Aggregated performance counters for the tagging subsystem. */
export interface TaggingMetrics {
  count: number;
  avgBeetsConfidence: number;
  sourceBreakdown: Record<string, number>;
}

/** Snapshot of runtime performance and health data for the settings screen. */
export interface SystemMetrics {
  search: SearchMetrics;
  download: DownloadMetrics;
  tagging: TaggingMetrics;
  ytdlpVersion: string;
  gcLastRun: string; // ISO 8601 datetime
  rawFolderSizeBytes: number;
}

/** Frontend error payload posted to the backend error-collection endpoint. */
export interface ClientErrorReport {
  requestId: string;
  error: string;
  stack: string;
  component?: string;
  route: string;
  userAgent: string;
  timestamp: string; // ISO 8601 datetime
}

/** Result of a yt-dlp auto-update or manual update attempt. */
export interface YtdlpUpdateStatus {
  currentVersion: string;
  updated: boolean;
  newVersion?: string;
}

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

/** Declaration of a source plugin's identity, capabilities, and supported formats. */
export interface PluginManifest {
  id: string;
  name: string;
  version: string;
  baseUrl: string;
  capabilities: PluginCapability[];
  searchInput: PluginSearchInput[];
  audioFormats: string[];
  icon: string;
}
