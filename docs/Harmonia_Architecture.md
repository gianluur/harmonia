HARMONIA
Self-Hosted Music Platform
Architecture & Design Specification
v1.2  ·  March 2026  ·  Performance, Privacy & Security hardening
1. Vision & Goals
Harmonia is a self-hosted music platform that merges two distinct services — Navidrome (library streaming) and a YouTube-based acquisition pipeline — into a single, cohesive application. The result should feel like Spotify or Apple Music: no seams, no "replacement" feel, just a first-class music experience running entirely on hardware you own.
Core principles:
One app, one interface. The user never needs to know that two backends exist.
Instant gratification. Songs stream while they download; the user does not wait.
Permanent ownership. Every acquired song lands in a properly tagged, organised local library.
Extensibility. A defined plugin contract means new source backends can be added without touching the frontend.
Privacy by default. No analytics, no direct third-party calls from the frontend. All external metadata and asset requests are proxied through the backend.
2. High-Level Architecture
Harmonia is composed of four distinct layers:

| Layer               | Technology                     | Responsibility                                                                                               |
| ------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Frontend            | Next.js + Tailwind + shadcn/ui | PWA, UI, Subsonic API client, plugin orchestration                                                           |
| Navidrome           | Navidrome (existing)           | Library management, Subsonic API, transcoding                                                                |
| Acquisition Backend | Python (FastAPI)               | yt-dlp download, streaming proxy, beets tagging, MusicBrainz/Cover Art Archive proxy, metadata privacy layer |
| File System         | Host OS                        | raw/ staging folder, library/ Navidrome folder                                                               |

The frontend communicates with Navidrome exclusively via the Subsonic API (OpenSubsonic spec). It communicates with the Acquisition Backend via a REST + WebSocket interface defined in Section 4. Navidrome is never aware of the Acquisition Backend and vice versa — the frontend is the only integration point.
3. Complete Data Flow
3.1 Search Flow
Search uses a streamed results model. Navidrome library results appear instantly; YouTube results stream in as they resolve. The user never waits for a blank screen.
User types a query (text) or pastes a YouTube URL into the search bar.
Frontend simultaneously: (a) queries Navidrome via GET /rest/search3 and renders library results immediately, and (b) opens a WebSocket to ws://<backend>/ws/search and sends POST /api/search.
Backend calls yt-dlp with --flat-playlist --dump-json. The --flat-playlist flag fetches only basic entry data (title, URL, duration, thumbnail) without opening each video for deep metadata extraction. This reduces search latency by ~70% compared to full metadata extraction.
As each YouTube result resolves, the backend pushes a search_result WebSocket event. The frontend appends results to the modal in real time — the list builds as the user watches.
Results from both sources are visually distinguished by a source badge (library icon vs YouTube icon) but share identical card styling.
3.2 Acquisition & Streaming Flow
Once the user selects a candidate from search results:
Frontend sends POST /api/acquire { youtube_id, title_hint } to the Acquisition Backend. Response includes { job_id, stream_token } — a short-lived signed token (10-minute expiry) scoped to this job.
Backend starts yt-dlp download to /data/raw/<job_id>/. Simultaneously it opens an HTTP chunked/range-capable stream endpoint at GET /api/stream/<job_id>?token=<stream_token>.
Frontend immediately begins playing from the stream URL — the user hears audio within 2–5 seconds. The stream token prevents the endpoint from being used as a public proxy or shared externally.
A WebSocket connection is opened to ws://<backend>/ws/<job_id> to receive real-time job events (download progress, tagging suggestions, completion).
The tagging panel slides up while music plays (see Section 3.3).
When yt-dlp finishes, the backend runs beets import --nowrite --timid on the file against MusicBrainz.
beets confidence score and metadata candidates are pushed via WebSocket event type: tagging_suggestions.
The tagging panel is pre-filled with the highest-confidence beets suggestion.
3.3 Tagging Flow
The tagging panel is a bottom sheet on mobile and a side panel on desktop. It appears automatically once the stream starts. It is non-blocking — the user can dismiss it and return to it later from a "Pending" tray.
Panel fields: Title, Artist, Album, Year, Track Number, Disc Number, Genre, Cover Art.
All fields are pre-filled from beets suggestions. Confidence is shown as a small percentage badge on each field.
The user can fuzzy-search any field: typing in the Artist field triggers GET /api/metadata/search?type=artist&query=... on the backend, which proxies to MusicBrainz /ws/2/artist (300 ms debounce). Results appear in a floating dropdown below the field. The frontend never calls MusicBrainz directly.
Selecting a MusicBrainz artist auto-populates the Album field with a release selector from that artist's discography.
Selecting a release auto-fills Year, Track Number, and fetches cover art via GET /api/metadata/coverart/:mbid — the backend proxies the Cover Art Archive request, strips identifying headers, and returns the image. The frontend never calls Cover Art Archive directly.
The user can override any field manually. Free-text overrides are stored in a local SQLite database called the Custom Metadata Store (Section 6.3).
If the song is niche and MusicBrainz has no results, every field can be filled manually. These entries are persisted and auto-suggested for future identical or similar queries via fuzzy string matching.
When the user taps Confirm, a PATCH /api/acquire/<job_id>/tags request is sent with the finalised metadata.
The backend writes ID3/Vorbis tags to the file using Mutagen, moves the file from /data/raw/<job_id>/ to /data/library/<Artist>/<Album>/<Track> - <Title>.ext, and triggers a Navidrome rescan via POST /rest/startScan.
A WebSocket event type: library_ready is pushed. The frontend refreshes the library and the song appears as a normal Navidrome track.
3.4 Folder Structure
/data/
raw/
<job_id>/
audio.webm          # yt-dlp in-progress or complete
audio.opus          # converted by yt-dlp post-processor
job.json            # job metadata (status, youtube_id, hints)
library/                # Navidrome music root
<Artist>/
<Album> (Year)/
01 - <Title>.opus
custom_metadata.db      # SQLite: user-defined tags
4. Acquisition Backend API
4.1 REST Endpoints

| Method | Path                         | Description                                                                                                                                                    |
| ------ | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | /api/search                  | Search YouTube. Body: { query: string } or { url: string }. Pushes search_result events via WebSocket as results stream in. Returns { search_id }.             |
| POST   | /api/acquire                 | Start acquisition job. Body: { youtube_id, title_hint? }. Returns { job_id, stream_token } — stream_token is a signed 10-minute token for the stream endpoint. |
| GET    | /api/stream/:job_id          | Chunked audio stream. Supports Range header for seek. Requires valid ?token= query param (ephemeral, 10-min expiry). Streams from partial yt-dlp output.       |
| GET    | /api/jobs/:job_id            | Job status. Returns JobStatus object.                                                                                                                          |
| PATCH  | /api/acquire/:job_id/tags    | Submit confirmed tags. Body: TagPayload. Triggers file move and Navidrome rescan.                                                                              |
| GET    | /api/metadata/search         | Backend proxy to MusicBrainz. Params: type (artist|release|recording), query. Strips identifying headers before forwarding. Returns MB candidates.             |
| GET    | /api/metadata/coverart/:mbid | Backend proxy to Cover Art Archive. Strips Referer and forwards a controlled User-Agent. Returns image bytes.                                                  |
| GET    | /api/custom-metadata/suggest | FTS5 fuzzy-match query against Custom Metadata Store. Returns stored tag suggestions.                                                                          |
| GET    | /api/jobs/pending            | List all jobs awaiting tag confirmation.                                                                                                                       |
| POST   | /api/system/update-ytdlp     | Manually trigger a yt-dlp update. Also called automatically by the 24-hour background worker.                                                                  |

4.2 WebSocket Events
WebSocket URL: ws://<backend>/ws/<job_id>
All events are JSON with a type field. Server → Client unless noted.

| Event type          | Payload & meaning                                                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| search_result       | { result: SearchResult } — pushed per YouTube result as --flat-playlist resolves each entry. Frontend appends to search modal in real time. |
| search_complete     | { search_id, total: number } — all YouTube results have been pushed.                                                                        |
| download_progress   | { percent: number, speed: string, eta: number } — shown in tagging panel progress bar.                                                      |
| download_complete   | { job_id, file_path } — download finished, beets import starting.                                                                           |
| tagging_suggestions | { candidates: TagCandidate[] } — beets results ranked by confidence. Each candidate includes all tag fields + confidence 0–1.               |
| tagging_error       | { message } — beets/MusicBrainz lookup failed. Panel falls back to manual entry.                                                            |
| library_ready       | { navidrome_id, file_path } — file moved, Navidrome rescan complete. Frontend refreshes library.                                            |
| job_error           | { message, recoverable: bool } — generic error. If recoverable, user can retry.                                                             |

5. Plugin Contract (Source Backend Spec)
The frontend does not care how a source backend works internally. It only requires that any source backend exposes the following interface. This allows future backends (e.g. a Bandcamp scraper, a local file importer, a SoundCloud plugin) to be added without modifying the frontend.
5.1 Plugin Manifest
Each plugin is a JSON file mounted or registered at startup:
{
"id": "youtube",
"name": "YouTube",
"version": "1.0.0",
"base_url": "http://localhost:8001",
"capabilities": ["search", "stream", "acquire"],
"search_input": ["query", "url"],
"audio_formats": ["opus", "mp3"],
"icon": "/icons/youtube.svg"
}
5.2 Required Endpoints
Every plugin that declares capability search must implement POST /api/search returning SearchResult[].
Every plugin that declares capability acquire must implement POST /api/acquire, GET /api/stream/:job_id, PATCH /api/acquire/:job_id/tags, and the WebSocket protocol from Section 4.
5.3 SearchResult Schema
{
"id": string,            // plugin-scoped unique ID
"title": string,
"artist": string,        // best-effort, may be empty
"duration_seconds": number,
"thumbnail_url": string,
"source_plugin": string, // plugin id
"source_url": string,    // original URL
"year": number | null
}
5.4 TagPayload Schema
{
"title": string,
"artist": string,
"album": string,
"year": number | null,
"track_number": number | null,
"disc_number": number | null,
"genre": string | null,
"cover_art_url": string | null,   // fetched by backend
"cover_art_b64": string | null,   // user-uploaded fallback
"mb_recording_id": string | null, // MusicBrainz MBID if matched
"mb_release_id": string | null
}
6. Frontend Architecture
6.1 Stack & Structure
Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui
PWA: next-pwa or custom service worker. Offline support for cached library tracks.
State: Zustand for global player state, React Query (TanStack Query) for Subsonic API calls and cache.
Audio: HTML5 <audio> element wrapped in a custom hook (usePlayer). No external audio library — keeps bundle small and behaviour predictable.
Directory structure:
src/
app/                  # Next.js App Router pages
components/
player/             # MiniPlayer, FullPlayer, Queue
library/            # AlbumGrid, ArtistList, TrackTable
search/             # SearchModal, SearchResult, SourceBadge
tagging/            # TaggingPanel, MetadataField, MBSuggest
ui/                 # shadcn components
hooks/
usePlayer.ts        # Audio playback, queue, shuffle, repeat
useSubsonic.ts      # Subsonic API client hook
useAcquisition.ts   # WS connection, job state
lib/
subsonic.ts         # Subsonic API wrapper
acquisition.ts      # Acquisition backend client
plugins.ts          # Plugin registry and dispatch
store/
player.ts           # Zustand player store
queue.ts            # Zustand queue store
6.2 Design System
The visual language is a modern, minimal glassmorphism. It must look identical and excellent on both iOS Safari and Android Chrome — no platform-conditional styles.
Palette: Deep navy (#1A1A2E) base, white/10 glass surfaces, accent in electric indigo (#6C63FF), success in emerald (#10B981).
Typography: Inter variable font. Track titles at 15px medium. Artist/album at 13px regular, muted.
Glass surfaces: backdrop-filter: blur(20px), background: rgba(255,255,255,0.06), border: 1px solid rgba(255,255,255,0.12).
Radius: 16px for cards, 24px for sheets, 9999px for pills.
Motion: Framer Motion. Sheet slides in from bottom (mobile) or right (desktop) with spring easing. No bounce on iOS — use ease-out instead.
Icons: Lucide React. Consistent 20px stroke icons throughout.
Bottom navigation on mobile (5 items max). Left sidebar on desktop. Both use the same Zustand state.
6.3 Player
The player has three states: hidden (no track loaded), mini bar (docked at bottom), and full screen (modal/sheet overlay). The mini bar is always visible once a track is playing, sitting above the bottom nav on mobile.
Queue management: drag-to-reorder, swipe-to-remove, shuffle, repeat (off/one/all).
Scrubber: custom canvas-based waveform or a simple styled range input with buffered progress indicator.
Streaming indicator: a subtle animated ring on the album art when playing from /api/stream (acquisition) vs a solid ring for Navidrome tracks. This is the only visible seam between the two backends.
When library_ready fires, the player silently switches the source from /api/stream to the Navidrome stream URL without interrupting playback.
6.4 Tagging Panel
The tagging panel is a bottom sheet (mobile) or right-side drawer (desktop ≥ 1024px). It appears automatically 3 seconds after streaming begins, sliding in with a spring animation.
A confidence bar at the top shows overall beets match confidence with colour coding: green ≥ 85%, yellow 60–84%, red < 60%.
Each field shows its individual confidence as a small badge. Low-confidence fields are highlighted with a subtle amber ring.
MusicBrainz fuzzy search is triggered on any text field with ≥ 2 characters. Results appear in a floating dropdown below the field.
Cover art: shown as a 64px square. Tapping opens a fullscreen picker with MB candidates + upload option.
A Pending tray (bell icon in nav) shows all jobs awaiting tag confirmation. Useful if the user dismisses the panel.
Confirming tags closes the panel and shows a toast notification when the track appears in the library.
6.5 Library Features
Since Navidrome exposes the full Subsonic API, all standard library features are supported:
Playlists: create, edit, reorder, delete via Subsonic playlist endpoints.
Favourites (stars): toggle via /rest/star and /rest/unstar. Synced to Navidrome.
Sort: by title, artist, album, year, date added, play count, rating.
Album view: grid with cover art. Artist view: discography list. Genre view: tag-based filter.
Offline: service worker caches the most-recently-played 50 tracks for offline playback. Navidrome download endpoint is used for pre-caching. Cache is scoped strictly to the application origin. Cache-Control: no-store is set on the live stream buffer to prevent raw acquisition streams from being persisted. Note: browser cache storage is not encrypted at the application level — device encryption (FileVault, Android FDE) is the correct layer for protecting cached audio on shared or stolen hardware.
7. Custom Metadata Store
The Custom Metadata Store is a SQLite database at /data/custom_metadata.db managed by the Acquisition Backend. Its purpose is to remember user-defined metadata for songs that MusicBrainz does not know about, and to auto-suggest that metadata for future similar queries.
7.1 Schema
The custom_tracks table uses SQLite FTS5 (Full Text Search) with a trigram tokenizer for fuzzy lookups. This replaces in-memory rapidfuzz matching, which would degrade as the store grows — FTS5 performs fuzzy lookups across thousands of entries in milliseconds, offloading work from the Python runtime entirely.
CREATE VIRTUAL TABLE custom_tracks_fts USING fts5(
title, artist, album, source_query,
content=custom_tracks,
tokenize='trigram'
);
CREATE TABLE custom_tracks (
id           INTEGER PRIMARY KEY,
title        TEXT NOT NULL,
artist       TEXT,
album        TEXT,
year         INTEGER,
genre        TEXT,
source_query TEXT,  -- original search query or URL
youtube_id   TEXT,
created_at   TEXT DEFAULT (datetime('now'))
);
7.2 Suggestion Logic
When the user opens the tagging panel for a new track, the backend:
Runs an FTS5 trigram query against custom_tracks_fts matching on title and source_query fields.
Returns matches above a BM25 score threshold as additional suggestions in the tagging_suggestions WebSocket event, tagged with source: 'custom'.
These appear in the suggestions dropdown with a bookmark icon to distinguish them from MusicBrainz results.
On INSERT or UPDATE to custom_tracks, triggers keep custom_tracks_fts in sync automatically.
8. Deployment
8.1 Docker Compose Layout
services:
navidrome:
image: deluan/navidrome:latest
volumes:
- ./data/library:/music:ro
- navidrome_data:/data
harmonia-backend:
build: ./backend
volumes:
- ./data:/data
environment:
- NAVIDROME_URL=http://navidrome:4533
- NAVIDROME_ADMIN_USER=admin
- NAVIDROME_ADMIN_PASS=<password>
- JWT_SECRET=<openssl rand -hex 32>
- JWT_EXPIRY_DAYS=30
harmonia-frontend:
build: ./frontend
environment:
- NEXT_PUBLIC_NAVIDROME_URL=https://music.yourdomain.com
- NEXT_PUBLIC_BACKEND_URL=https://music.yourdomain.com/api
8.2 Environment Variables

| Variable                  | Service  | Description                                                         |
| ------------------------- | -------- | ------------------------------------------------------------------- |
| NAVIDROME_URL             | Backend  | Internal Navidrome URL for rescan API calls                         |
| NAVIDROME_ADMIN_USER      | Backend  | Navidrome admin credentials for rescan                              |
| NAVIDROME_ADMIN_PASS      | Backend  | Navidrome admin credentials for rescan                              |
| JWT_SECRET                | Backend  | Random secret for signing JWTs. Generate with: openssl rand -hex 32 |
| JWT_EXPIRY_DAYS           | Backend  | JWT lifetime in days. Default: 30                                   |
| MUSIC_LIBRARY_PATH        | Backend  | Absolute path to /data/library                                      |
| RAW_PATH                  | Backend  | Absolute path to /data/raw                                          |
| MUSICBRAINZ_APP_NAME      | Backend  | App name for MusicBrainz User-Agent header                          |
| NEXT_PUBLIC_NAVIDROME_URL | Frontend | Public-facing Navidrome URL for Subsonic API                        |
| NEXT_PUBLIC_BACKEND_URL   | Frontend | Public-facing Acquisition Backend URL                               |

9. Security & Privacy Hardening
9.1 Backend Metadata Proxy
The frontend never makes direct requests to any external service. All outbound calls to MusicBrainz and the Cover Art Archive are routed through the Acquisition Backend. This enforces the privacy-by-default principle: the user's home IP and musical interests are never exposed to third parties.
Header policy for outbound proxy requests:
Referer: stripped entirely. Never forwarded.
User-Agent: replaced with a controlled value identifying Harmonia (e.g. 'Harmonia/1.0 (self-hosted; contact: harmonia-mb@example.com)'). MusicBrainz requires a descriptive User-Agent per their API policy — this is the only identifying header sent, and it identifies the software, not the instance or user.
X-Forwarded-For, X-Real-IP, Cookie, Authorization: all stripped before forwarding.
No request body data beyond the query is forwarded.
9.2 Navidrome Non-Admin User
The frontend authenticates against Navidrome using a dedicated non-admin user account. This account has read/write access to the library (play, star, playlist management) but cannot delete tracks, modify server settings, or manage other users. The admin credentials used for POST /rest/startScan are held only by the backend and never exposed to the frontend or browser.
Two Navidrome credentials are therefore required at setup:
NAVIDROME_ADMIN_USER / NAVIDROME_ADMIN_PASS — backend only, used exclusively for library rescans.
NAVIDROME_APP_USER / NAVIDROME_APP_PASS — frontend, used for all Subsonic API calls. Non-admin account created manually in Navidrome.
9.3 Ephemeral Stream Tokens
The acquisition stream endpoint GET /api/stream/:job_id requires a short-lived signed token passed as a query parameter (?token=...). Tokens are HMAC-SHA256 signed using the JWT_SECRET, scoped to a specific job_id, and expire after 10 minutes. The token is issued in the POST /api/acquire response and used only by the frontend's audio element for that session. This prevents:
The stream URL being shared externally or bookmarked as a persistent open proxy.
Other network clients on the same LAN accessing acquisition streams without authentication.
9.4 yt-dlp Stability & Auto-Update
YouTube's obfuscation logic changes frequently and silently. A broken yt-dlp version is the single most likely production failure mode for Harmonia. Two mitigations are implemented:
Background update worker: a lightweight APScheduler job runs every 24 hours inside the backend container, executing pip install -U yt-dlp --break-system-packages. The result (success, already-up-to-date, or failure) is logged and surfaced in GET /api/system/status.
Manual trigger: POST /api/system/update-ytdlp allows the user to force an immediate update from the settings screen without restarting the container.
Node.js is NOT listed as a hard runtime requirement. Recent yt-dlp versions ship their own JavaScript interpreter for signature challenges. This should be verified against the yt-dlp release in use and documented in the deployment README, but it is not enforced in the Dockerfile.
9.5 PWA Cache Security Scope
The service worker enforces the following cache policy:
Cache-Control: no-store is set on all responses from /api/stream/* to prevent raw acquisition audio from being persisted in the browser cache.
The offline library cache (last 50 played tracks from Navidrome) is scoped to the application origin. No cross-origin cache sharing is possible by the service worker spec.
Browser cache storage is not encrypted at the application level. This is a documented known limitation — the correct protection layer is OS-level device encryption (FileVault on macOS, Android FDE, BitLocker on Windows). Implementing Web Crypto API encryption in the browser would provide no meaningful protection on a device with filesystem access, as both ciphertext and key would be co-located in the same browser profile.
10. Finalised Decisions
All architectural decisions have been resolved. This section serves as the definitive record.

| Topic                            | Decision                                                                                                                                                                                                                                                                                                              |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Audio format                     | Opus (default yt-dlp output). No preemptive transcoding. If platform compatibility issues are discovered during testing on iOS, Android, or web, add an optional transcode step — this is a single beets config change and a minor backend addition.                                                                  |
| Authentication                   | First-run setup screen sets username and password. Credentials are bcrypt-hashed and stored in the config table of custom_metadata.db. Subsequent visits show a login screen. Successful login issues a 30-day JWT stored in an httpOnly cookie (XSS-safe). Auto-renews on activity. Manual logout clears the cookie. |
| Navidrome credentials            | Shared via env vars NAVIDROME_ADMIN_USER and NAVIDROME_ADMIN_PASS in the backend container. Used exclusively for triggering POST /rest/startScan after a file is moved to the library.                                                                                                                                |
| User model                       | Single-user. No user_id columns anywhere. No multi-tenancy.                                                                                                                                                                                                                                                           |
| Background audio & notifications | Media Session API handles all OS integration: lock screen controls, headphone buttons, Bluetooth/car display, system now-playing widget. No push notifications. Download and tagging events surface only as silent in-app toasts — never as OS notifications.                                                         |
| Backend network exposure         | The auth screen makes the app safe regardless of network topology (Tailscale, reverse proxy, LAN). No additional network-level restrictions are enforced by the app itself.                                                                                                                                           |

11. Authentication Detail
10.1 First-Run Setup Flow
On first launch, the SQLite config table is empty. The frontend detects this via GET /api/auth/status returning { configured: false } and redirects to /setup. The setup screen is a full-page form asking for a username and password (with confirmation). On submit:
POST /api/auth/setup { username, password } is called.
Backend bcrypt-hashes the password (cost factor 12) and writes one row to the config table.
Response issues a 30-day httpOnly JWT cookie.
Frontend redirects to / (the main app). The setup screen is never reachable again.
10.2 Login Flow
On subsequent visits, GET /api/auth/status returns { configured: true }. If no valid JWT cookie is present, the frontend redirects to /login. The login screen is minimal — username + password, a single button, no "forgot password" (self-hosted, single-user). On submit:
POST /api/auth/login { username, password } is called.
Backend verifies bcrypt hash. On success, issues a fresh 30-day httpOnly JWT cookie.
Frontend redirects to the originally requested page.
10.3 JWT Middleware
All acquisition backend routes (except /api/auth/* and /api/stream/:job_id with a valid token param) are protected by JWT middleware. The frontend attaches credentials automatically via the cookie — no Authorization header needed. The stream endpoint accepts an optional ?token= query param to support the HTML5 audio element, which cannot set headers.
10.4 Config Table Schema
CREATE TABLE config (
key    TEXT PRIMARY KEY,
value  TEXT NOT NULL
);
-- Rows: ('username', 'alice'), ('password_hash', '$2b$12$...')
12. Implementation Roadmap

| Phase | Name             | Deliverables                                                                                                                                                                                                                                                     |
| ----- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Backend Core     | FastAPI skeleton, auth endpoints (setup/login/JWT middleware), yt-dlp --flat-playlist search with WebSocket streaming, yt-dlp download + chunked stream proxy with ephemeral tokens, WebSocket job events, raw/ folder management, 24h yt-dlp auto-update worker |
| 2     | Tagging Pipeline | beets integration, MusicBrainz + Cover Art Archive backend proxy with header sanitisation, FTS5 Custom Metadata Store + trigram suggestions, PATCH tags → Mutagen write → file move → Navidrome rescan (non-admin + admin credential split)                      |
| 3     | Frontend Shell   | Next.js + PWA setup, design system tokens, auth screens (setup + login), layout (nav + player bar), Subsonic client hook using non-admin Navidrome user, library views (albums, artists, tracks, genres)                                                         |
| 4     | Player           | Full player modal, mini bar, queue (drag-reorder, swipe-remove), shuffle/repeat, Media Session API integration, silent source switch (stream → Navidrome on library_ready), Cache-Control: no-store on stream buffer                                             |
| 5     | Acquisition UI   | Search modal with streamed results (Navidrome instant + YouTube via WebSocket), acquisition trigger, tagging panel (bottom sheet / side drawer), MusicBrainz fuzzy fields via backend proxy, cover art picker, pending tray                                      |
| 6     | Polish & PWA     | Service worker offline cache (last 50 tracks, origin-scoped), PWA install prompt, mobile gestures, accessibility audit, Opus platform testing (iOS/Android/web), settings screen with manual yt-dlp update trigger                                               |
| 7     | Plugin System    | Plugin manifest loader, frontend plugin registry, abstract source dispatch — enables adding future source backends without frontend changes                                                                                                                      |

Each phase is independently deployable. After Phase 1 you have a working acquisition API you can curl. After Phase 2 you have a complete CLI pipeline. After Phase 4 you have a working music player. Phase 5 is where the two halves merge into a single cohesive product.
End of Specification  ·  Harmonia v1.2  ·  Performance, Privacy & Security hardening applied