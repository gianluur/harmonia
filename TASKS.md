# Harmonia — Implementation Tasks

## How to use this file
Each task = one file. Work top to bottom. Do not skip ahead.
Before starting any task: read CLAUDE.md.
After completing any task: mark it `[x]`, commit, move to the next.

### Agent prompt to use at the start of each session:
```
Read CLAUDE.md then read TASKS.md. Find the first unchecked task,
implement it, run the specified test command, fix all failures,
then mark the task [x]. Stop after one task.
```

---

## Phase 1 — Backend Core

### 1.1 Job Store
- [x] **`backend/services/job_store.py`**
  - Read: `docs/Harmonia_Architecture.md` sections 7.1, 7.2 (jobs table + state machine)
  - Read: `backend/database.py` (AsyncDB query helpers)
  - Read: `backend/schemas.py` (JobStatusEnum, JobStatus)
  - Implement: `create_job()`, `get_job()`, `update_job_status()`, `list_pending_jobs()`, `StateTransitionError`
  - State machine must reject illegal transitions
  - Test: `cd backend && pytest tests/unit/test_job_store.py -v`

### 1.2 Auth unit tests
- [x] **`backend/tests/unit/test_auth.py`**
  - Read: `backend/auth.py` (all functions already implemented)
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.1 (exact test names)
  - Implement all 9 tests from the spec: password hash/verify, JWT roundtrip/expiry/wrong secret, stream token roundtrip/expiry/wrong job
  - Test: `cd backend && pytest tests/unit/test_auth.py -v`

### 1.3 Job store unit tests
- [x] **`backend/tests/unit/test_job_store.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.7 (exact test names)
  - Read: `backend/services/job_store.py` (just implemented)
  - Implement all 8 tests: valid transitions, invalid transitions, error/retry transitions
  - Test: `cd backend && pytest tests/unit/test_job_store.py -v`

### 1.4 yt-dlp service
- [x] **`backend/services/ytdlp.py`**
  - Read: `docs/Harmonia_Architecture.md` section 3.1 (search flow), 3.2 (acquisition flow)
  - Read: `backend/plugin_base.py` (DownloadEvent types)
  - Read: `backend/schemas.py` (SearchResult)
  - Implement: `run_search(query, search_id, log) -> AsyncGenerator[SearchResult]`
  - Implement: `run_download(job_id, youtube_id, raw_dir, log) -> AsyncGenerator[DownloadEvent]`
  - Use `asyncio.create_subprocess_exec` — never `subprocess.run`
  - Always pass `--flat-playlist` for search
  - Test: `cd backend && pytest tests/unit/ -v -k ytdlp` (unit tests only, no integration yet)

### 1.5 Job WebSocket handler
- [x] **`backend/ws/job.py`**
  - Read: `docs/Harmonia_Architecture.md` section 4.2.1 (job WS protocol)
  - Read: `backend/services/job_store.py` (get_job, update_job_status)
  - Read: `backend/schemas.py` (all JobWSEvent types)
  - Implement: WS endpoint `ws/<job_id>?request_id=<uuid>`
  - On connect: send current JobStatus as first message
  - Fan-out download events to connected clients
  - Reconnection: resume from current job state
  - Close with code 4001 on invalid JWT
  - Test: `cd backend && pytest tests/integration/test_acquire_api.py -v -k ws`

### 1.6 Search WebSocket handler
- [x] **`backend/ws/search.py`**
  - Read: `docs/Harmonia_Architecture.md` section 4.2.2 (search WS protocol)
  - Read: `backend/services/ytdlp.py` (run_search)
  - Read: `backend/schemas.py` (SearchWSEvent types)
  - Implement: WS endpoint `ws/search?request_id=<uuid>`
  - Accept: `{type: "search", query?, url?, search_id}` message
  - Push `search_result` events as yt-dlp resolves each entry
  - Push `search_complete` when done
  - Close idle connections after 60 seconds
  - Test: `cd backend && pytest tests/integration/test_search_api.py -v`

### 1.7 Acquire router
- [x] **`backend/routers/acquire.py`**
  - Read: `backend/routers/auth.py` (ALL patterns to follow)
  - Read: `docs/Harmonia_Architecture.md` section 4.1.2 (exact endpoints, status codes)
  - Read: `backend/services/job_store.py`, `backend/auth.py` (encode_stream_token)
  - Implement: `POST /api/acquire` → 201, `GET /api/stream/:job_id`, `GET /api/jobs/:job_id`, `GET /api/jobs/pending`, `PATCH /api/acquire/:job_id/tags`
  - Stream endpoint: validate stream token, support Range header, return 206 for ranges
  - Uncomment acquire router in `backend/main.py` after implementing
  - Test: `cd backend && pytest tests/integration/test_acquire_api.py -v`
  - Note: list_pending_jobs() should return status != 'confirmed', not just status = 'pending'

### 1.8 Search router
- [x] **`backend/routers/search.py`**
  - Read: `backend/routers/auth.py` (patterns)
  - Read: `docs/Harmonia_Architecture.md` section 4.1.2 (POST /api/search)
  - Implement: `POST /api/search` → 200 `{search_id}`, initiates WS search session
  - Uncomment search router in `backend/main.py` after implementing
  - Test: `cd backend && pytest tests/integration/test_search_api.py -v`

### 1.9 Auth integration tests
- [ ] **`backend/tests/integration/test_auth_api.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.1 (all 11 test scenarios)
  - Read: `backend/tests/conftest.py` (client, auth_client fixtures)
  - Implement all 11 tests including request_id header tests and error envelope shape test
  - Test: `cd backend && pytest tests/integration/test_auth_api.py -v`

---

## Phase 2 — Tagging Pipeline

### 2.1 Proxy header sanitisation
- [ ] **`backend/services/proxy.py`**
  - Read: `docs/Harmonia_Architecture.md` section 9.1 (header policy)
  - Read: `backend/config.py` (musicbrainz_user_agent property)
  - Implement: `sanitise_headers()`, `search_musicbrainz()`, `get_coverart()`
  - Strip: Referer, X-Forwarded-For, X-Real-IP, Cookie, Authorization
  - Replace User-Agent with controlled Harmonia string
  - 5 second timeout on all outbound requests
  - Test: `cd backend && pytest tests/unit/test_proxy.py -v`

### 2.2 Proxy unit tests
- [ ] **`backend/tests/unit/test_proxy.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.3 (6 test names)
  - Implement all 6 tests
  - Test: `cd backend && pytest tests/unit/test_proxy.py -v`

### 2.3 Tagger service
- [ ] **`backend/services/tagger.py`**
  - Read: `docs/Harmonia_Architecture.md` section 3.3 (tagging flow), section 10 (path sanitisation ADR)
  - Read: `backend/schemas.py` (TagPayload, TagCandidate)
  - Implement: `run_beets()`, `write_tags()`, `build_library_path()`, `sanitise_path_component()`
  - Path sanitisation: replace `/ \ : * ? " < > |` and leading `.` with `-`, max 200 chars
  - Test: `cd backend && pytest tests/unit/test_tagging.py -v`

### 2.4 Tagger unit tests
- [ ] **`backend/tests/unit/test_tagging.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.2 (12 test names)
  - Implement all 12 tests including path sanitisation edge cases
  - Test: `cd backend && pytest tests/unit/test_tagging.py -v`

### 2.5 Custom metadata store
- [ ] **`backend/services/custom_meta.py`**
  - Read: `docs/Harmonia_Architecture.md` section 7 (FTS5 schema, suggestion logic)
  - Read: `backend/database.py` (AsyncDB helpers)
  - Implement: `CustomMetadataStore` class with `suggest()` and `save()`
  - FTS5 trigram search on title + source_query fields
  - Test: `cd backend && pytest tests/unit/test_fts.py -v`

### 2.6 FTS5 unit tests
- [ ] **`backend/tests/unit/test_fts.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.4 (5 test names)
  - Implement all 5 tests
  - Test: `cd backend && pytest tests/unit/test_fts.py -v`

### 2.7 Navidrome service
- [ ] **`backend/services/navidrome.py`**
  - Read: `docs/Harmonia_Architecture.md` section 3.3 (rescan step), section 9.2 (admin credentials)
  - Implement: `trigger_scan()` using NAVIDROME_ADMIN_USER/PASS
  - Returns navidrome_id after scan completes
  - Test: `cd backend && pytest tests/integration/test_tagging_api.py -v -k navidrome`

### 2.8 Metadata router
- [ ] **`backend/routers/metadata.py`**
  - Read: `backend/routers/auth.py` (patterns)
  - Read: `docs/Harmonia_Architecture.md` section 4.1.3
  - Implement: `GET /api/metadata/search`, `GET /api/metadata/coverart/:mbid`, `GET /api/custom-metadata/suggest`
  - Uncomment metadata router in `backend/main.py`
  - Test: `cd backend && pytest tests/integration/test_metadata_api.py -v`

### 2.9 Tagging integration tests
- [ ] **`backend/tests/integration/test_tagging_api.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.4 (10 test scenarios)
  - Implement all 10 tests
  - Test: `cd backend && pytest tests/integration/test_tagging_api.py -v`

### 2.10 Metadata integration tests
- [ ] **`backend/tests/integration/test_metadata_api.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.5 (9 test scenarios)
  - Implement all 9 tests including malformed response handling
  - Test: `cd backend && pytest tests/integration/test_metadata_api.py -v`

---

## Phase 3 — System & Observability

### 3.1 Metrics service
- [ ] **`backend/services/metrics.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 7.6 (metrics endpoint shape)
  - Read: `backend/schemas.py` (SystemMetrics)
  - Implement: rolling 24h in-memory buffer, `record_search/download/tagging/file_move/navidrome_scan()`, `get_metrics() -> SystemMetrics`
  - Thread-safe via `asyncio.Lock`
  - Test: `cd backend && pytest tests/unit/test_metrics.py -v`

### 3.2 Metrics unit tests
- [ ] **`backend/tests/unit/test_metrics.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.6 (5 test names)
  - Implement all 5 tests including rolling window and p95 calculation
  - Test: `cd backend && pytest tests/unit/test_metrics.py -v`

### 3.3 GC worker
- [ ] **`backend/workers/gc.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 7.8 (GC worker spec)
  - Read: `backend/config.py` (gc_raw_max_age_hours)
  - Implement: APScheduler job, runs every 6h, deletes raw/<job_id>/ folders older than threshold with status != confirmed and not tagging_in_progress
  - Log `gc_job_deleted` with freed_bytes before each deletion
  - Test: `cd backend && pytest tests/unit/test_gc_worker.py -v`

### 3.4 GC worker unit tests
- [ ] **`backend/tests/unit/test_gc_worker.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.1.5 (5 test names)
  - Implement all 5 tests
  - Test: `cd backend && pytest tests/unit/test_gc_worker.py -v`

### 3.5 GC worker integration tests
- [ ] **`backend/tests/integration/test_gc_worker.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.6 (6 test scenarios)
  - Implement all 6 tests including skip-active-tagging-job test
  - Test: `cd backend && pytest tests/integration/test_gc_worker.py -v`

### 3.6 yt-dlp updater worker
- [ ] **`backend/workers/ytdlp_updater.py`**
  - Read: `docs/Harmonia_Architecture.md` section 9.4
  - Implement: APScheduler job, runs every 24h, `pip install -U yt-dlp`, logs result
  - Uncomment both workers in `backend/main.py` lifespan after implementing
  - Test: manual verification — run worker, check log output

### 3.7 System router
- [ ] **`backend/routers/system.py`**
  - Read: `backend/routers/auth.py` (patterns)
  - Read: `docs/Harmonia_Architecture.md` section 4.1.4
  - Read: `backend/schemas.py` (SystemMetrics, YtdlpUpdateStatus, ClientErrorReport)
  - Implement: `GET /api/system/status`, `GET /api/system/metrics`, `POST /api/system/update-ytdlp`, `POST /api/logs/client`
  - Rate limit `/api/logs/client` to 10 req/min per IP using slowapi
  - Uncomment system router in `backend/main.py`
  - Test: `cd backend && pytest tests/integration/test_metrics_api.py tests/integration/test_client_logs_api.py -v`

### 3.8 Metrics integration tests
- [ ] **`backend/tests/integration/test_metrics_api.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.7 (6 test scenarios)
  - Implement all 6 tests
  - Test: `cd backend && pytest tests/integration/test_metrics_api.py -v`

### 3.9 Client logs integration tests
- [ ] **`backend/tests/integration/test_client_logs_api.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 4.8 (5 test scenarios)
  - Implement all 5 tests including rate limit test
  - Test: `cd backend && pytest tests/integration/test_client_logs_api.py -v`

### 3.10 Plugin registry
- [ ] **`backend/plugins.py`**
  - Read: `docs/Harmonia_Architecture.md` section 5 (plugin contract)
  - Read: `backend/plugin_base.py` (SourcePlugin ABC, PluginManifest)
  - Implement: `PluginRegistry` class with `load_plugins()` and `get_plugin(id)`
  - Validates each manifest against PluginManifest Pydantic schema on load
  - Test: `cd backend && pytest tests/contract/test_plugin_contract.py -v`

### 3.11 Full backend test suite — green check
- [ ] **Run full backend suite**
  - `cd backend && pytest tests/ -v --cov=backend --cov-report=term-missing`
  - All tests must pass
  - Coverage must meet thresholds from `docs/Harmonia_Testing_Observability.md` section 8.2
  - Fix any failures before proceeding to Phase 4

---

## Phase 4 — Frontend Shell

### 4.1 Subsonic client
- [ ] **`frontend/src/lib/subsonic.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 6.1 (Subsonic API usage)
  - Read: `frontend/src/lib/types.ts` (all types)
  - Implement: `buildAuthParams()`, `buildStreamUrl()`, `parseSearch3()`
  - Uses NAVIDROME_APP_USER/PASS from env
  - Test: `cd frontend && npm run test -- tests/unit/subsonic.test.ts`

### 4.2 Subsonic unit tests
- [ ] **`frontend/tests/unit/subsonic.test.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.2.1 (4 test names)
  - Implement all 4 tests
  - Test: `cd frontend && npm run test -- tests/unit/subsonic.test.ts`

### 4.3 Request ID middleware
- [ ] **`frontend/src/middleware.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 7.2a (request tracing)
  - Implement: generates UUID v4 on every outbound fetch, attaches as X-Request-ID header
  - Preserves existing header if caller already set it
  - Test: `cd frontend && npm run test -- tests/unit/requestId.test.ts`

### 4.4 Request ID unit tests
- [ ] **`frontend/tests/unit/requestId.test.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.2.3 (4 test names)
  - Implement all 4 tests
  - Test: `cd frontend && npm run test -- tests/unit/requestId.test.ts`

### 4.5 Acquisition client
- [ ] **`frontend/src/lib/acquisition.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 4.1 (all REST endpoints)
  - Read: `frontend/src/lib/types.ts`
  - Implement: thin fetch wrappers for all acquisition backend REST endpoints
  - All requests include X-Request-ID via middleware
  - Test: manual type-check `cd frontend && npx tsc --noEmit`

### 4.6 Player store
- [ ] **`frontend/src/store/player.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 6.3 (player states)
  - Read: `frontend/src/lib/types.ts`
  - Implement: Zustand store with currentTrack, isPlaying, volume, repeat, shuffle
  - Media Session API integration
  - Source switching without interrupting playback
  - Test: `cd frontend && npm run test -- tests/unit/player.test.ts`

### 4.7 Player unit tests
- [ ] **`frontend/tests/unit/player.test.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 3.2.2 (9 test names)
  - Implement all 9 tests including Media Session cleanup tests
  - Test: `cd frontend && npm run test -- tests/unit/player.test.ts`

### 4.8 Queue store
- [ ] **`frontend/src/store/queue.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 6.3 (queue management)
  - Implement: Zustand store with tracks[], add(), remove(), reorder(), next(), previous()
  - Test: `cd frontend && npx tsc --noEmit`

### 4.9 App layout and auth pages
- [ ] **`frontend/src/app/layout.tsx`**
  - Read: `frontend/src/components/ui/GlassCard.tsx` (design patterns)
  - Read: `frontend/src/app/globals.css`
  - Implement: root layout with QueryClientProvider, Zustand providers, Inter font
  - Test: `cd frontend && npx tsc --noEmit`

- [ ] **`frontend/src/app/page.tsx`**
  - Implement: redirects to /setup if not configured, /login if not authenticated

- [ ] **`frontend/src/app/setup/page.tsx`**
  - Read: `docs/Harmonia_Architecture.md` section 11.1
  - Implement: first-run setup form using GlassCard, calls POST /api/auth/setup

- [ ] **`frontend/src/app/login/page.tsx`**
  - Read: `docs/Harmonia_Architecture.md` section 11.2
  - Implement: login form using GlassCard, calls POST /api/auth/login

### 4.10 useSubsonic hook
- [ ] **`frontend/src/hooks/useSubsonic.ts`**
  - Implement: TanStack Query hooks wrapping all Subsonic endpoints
  - Test: `cd frontend && npx tsc --noEmit`

---

## Phase 5 — Player & Acquisition UI

### 5.1 usePlayer hook
- [ ] **`frontend/src/hooks/usePlayer.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 6.3 (source switch on library_ready)
  - Implement: HTML5 audio element management, ties to player store
  - Handles silent source switch from /api/stream to Navidrome URL on library_ready
  - Test: `cd frontend && npm run test -- tests/unit/player.test.ts`

### 5.2 useAcquisition hook
- [ ] **`frontend/src/hooks/useAcquisition.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 4.2 (WS protocol)
  - Implement: manages both job WS and search WS connections
  - Reconnect with exponential backoff (1s, 2s, 4s, max 30s)
  - Test: `cd frontend && npx tsc --noEmit`

### 5.3 MiniPlayer component
- [ ] **`frontend/src/components/player/MiniPlayer.tsx`**
  - Read: `frontend/src/components/ui/GlassCard.tsx` (ALL patterns)
  - Read: `docs/Harmonia_Architecture.md` section 6.3
  - Implement: docked mini bar, always visible once playing, sits above bottom nav
  - Streaming indicator ring (animated) for /api/stream vs solid for Navidrome
  - Uses GlassCard variant="elevated"
  - Test: `cd frontend && npx tsc --noEmit`

### 5.4 FullPlayer component
- [ ] **`frontend/src/components/player/FullPlayer.tsx`**
  - Read: `frontend/src/components/ui/GlassCard.tsx` (patterns)
  - Implement: full screen modal/sheet, queue view toggle
  - Test: `cd frontend && npx tsc --noEmit`

### 5.5 Queue component
- [ ] **`frontend/src/components/player/Queue.tsx`**
  - Implement: drag-to-reorder, swipe-to-remove
  - Test: `cd frontend && npx tsc --noEmit`

### 5.6 Library components
- [ ] **`frontend/src/components/library/AlbumGrid.tsx`**
- [ ] **`frontend/src/components/library/ArtistList.tsx`**
- [ ] **`frontend/src/components/library/TrackTable.tsx`**
  - Read: `frontend/src/components/ui/GlassCard.tsx` (patterns)
  - All use GlassCard variant="interactive" for cards
  - Test: `cd frontend && npx tsc --noEmit`

### 5.7 Search components
- [ ] **`frontend/src/components/search/SearchModal.tsx`**
  - Read: `docs/Harmonia_Architecture.md` section 3.1 (search flow)
  - Implement: Navidrome instant results + YouTube WS streaming, results build in real time
  - Test: `cd frontend && npx tsc --noEmit`

- [ ] **`frontend/src/components/search/SearchResult.tsx`**
  - Uses GlassCard variant="interactive"

- [ ] **`frontend/src/components/search/SourceBadge.tsx`**
  - Uses GlassCardBadge variant="accent" for YouTube, variant="success" for library

### 5.8 Tagging components
- [ ] **`frontend/src/components/tagging/TaggingPanel.tsx`**
  - Read: `docs/Harmonia_Architecture.md` section 6.4 (tagging panel spec)
  - Read: `frontend/src/components/ui/GlassCard.tsx` (ConfidenceBar pattern)
  - Implement: bottom sheet (mobile) / right drawer (desktop ≥ 1024px)
  - Appears 3s after streaming starts (TAGGING_PANEL_DELAY_MS from e2e/constants.ts)
  - Uses ConfidenceBar: green ≥ 85%, gold 60–84%, red < 60%
  - Test: `cd frontend && npx tsc --noEmit`

- [ ] **`frontend/src/components/tagging/MetadataField.tsx`**
  - Single tag field with confidence badge + MusicBrainz fuzzy dropdown
  - Uses GlassCard variant="inset" for field background

- [ ] **`frontend/src/components/tagging/MBSuggest.tsx`**
  - 300ms debounce on input, calls GET /api/metadata/search via acquisition client
  - Test: `cd frontend && npx tsc --noEmit`

### 5.9 Frontend type check — full pass
- [ ] **Full TypeScript check**
  - `cd frontend && npx tsc --noEmit`
  - Zero errors before proceeding to Phase 6

---

## Phase 6 — Polish & PWA

### 6.1 Service worker (replaces next-pwa)
- [ ] **Custom service worker**
  - Read: `docs/Harmonia_Architecture.md` section 9.5 (cache security scope)
  - Read: `docs/Harmonia_Testing_Observability.md` section 7.7 (cache invalidation strategy)
  - Implement: cache last 50 played tracks from Navidrome
  - Cache-Control: no-store on all /api/stream/* responses
  - Cache validation pass on app open: delete tracks no longer in Navidrome library

### 6.2 Settings screen
- [ ] **`frontend/src/app/settings/page.tsx`**
  - Shows system metrics from GET /api/system/metrics
  - Manual yt-dlp update trigger via POST /api/system/update-ytdlp

### 6.3 E2E tests — auth
- [ ] **`frontend/e2e/auth.spec.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 6.2 (5 test scenarios)
  - Read: `frontend/e2e/global-setup.ts` (test credentials setup)
  - Implement all 5 tests

### 6.4 E2E tests — acquisition
- [ ] **`frontend/e2e/acquisition.spec.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 6.3 (8 test scenarios)
  - Read: `frontend/e2e/constants.ts` (timing constants)
  - Implement all 8 tests including delayed library_ready race test

### 6.5 E2E tests — player
- [ ] **`frontend/e2e/player.spec.ts`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 6.4 (7 test scenarios)
  - Implement all 7 tests including PWA cache invalidation test

---

## Phase 7 — Plugin System

### 7.1 YouTube plugin (real implementation)
- [ ] **`backend/plugins/youtube.py`**
  - Read: `backend/plugin_base.py` (SourcePlugin ABC — implement all 4 abstract methods)
  - Read: `backend/services/ytdlp.py`, `backend/services/tagger.py`
  - Implement: real yt-dlp based `YouTubePlugin(SourcePlugin)`
  - Test: `cd backend && pytest tests/contract/test_plugin_contract.py -v`

### 7.2 Frontend plugin registry
- [ ] **`frontend/src/lib/plugins.ts`**
  - Read: `docs/Harmonia_Architecture.md` section 5 (plugin contract)
  - Implement: plugin registry that dispatches search/acquire to correct plugin

### 7.3 Contract tests — plugin
- [ ] **`backend/tests/contract/test_plugin_contract.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 5.1 (4 test names)
  - Implement all 4 tests parameterised over all installed plugins

### 7.4 Contract tests — internal API
- [ ] **`backend/tests/contract/test_internal_contract.py`**
  - Read: `docs/Harmonia_Testing_Observability.md` section 5.3 (5 test names)
  - Implement all 5 tests

### 7.5 Final — full test suite green
- [ ] **All tests passing**
  - `cd backend && pytest tests/ -v --cov=backend --cov-report=term-missing`
  - `cd frontend && npm run test`
  - `cd frontend && npm run e2e`
  - All coverage thresholds met (see Testing spec §8.2)
  - Zero TypeScript errors: `cd frontend && npx tsc --noEmit`