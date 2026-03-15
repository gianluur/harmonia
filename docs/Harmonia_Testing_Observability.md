HARMONIA
Testing & Observability Specification
v1.1  ·  March 2026  ·  Observability, resilience & safeguards hardening
1. Philosophy
Two rules govern every test and every log line in Harmonia:
If it can break silently, it must be tested. yt-dlp updates, MusicBrainz timeouts, malformed tags, a Navidrome rescan that returns 200 but does nothing — all of these are silent failures. Tests exist to surface them before the user does.
If a bug is hard to reproduce, logging failed. Every log line must carry enough context to reconstruct what happened without attaching a debugger. Log lines that say 'error occurred' are noise, not signal.
The test suite is divided into four layers. Each layer has a distinct purpose, speed contract, and failure meaning:

| Layer       | Tool              | Speed target    | A failure means...                                          |
| ----------- | ----------------- | --------------- | ----------------------------------------------------------- |
| Unit        | pytest / Vitest   | < 2 ms / test   | A function has wrong logic. Fix the function.               |
| Integration | pytest + HTTPX    | < 500 ms / test | Two components misunderstand each other. Fix the interface. |
| Contract    | pytest + Pydantic | < 100 ms / test | A plugin or API broke its public shape. Fix the schema.     |
| End-to-end  | Playwright        | < 30 s / test   | A real user flow is broken. Fix the product.                |

2. Mock & Fixture Strategy
All five external dependencies are mocked. No test ever makes a real network call or modifies the real filesystem. Each mock is defined once and shared across all test layers that need it.
2.1 yt-dlp Mock
yt-dlp is a subprocess call. It is mocked by patching the Python subprocess.run / asyncio.create_subprocess_exec call at the boundary, not by monkey-patching yt-dlp internals. This ensures the mock survives yt-dlp version changes.
Fixture files stored at tests/fixtures/ytdlp/:
search_flat.json — sample --flat-playlist --dump-json output for a 5-result search query.
download_complete.json — sample --dump-json output for a single video after full metadata extraction.
error_private_video.json — yt-dlp stderr output for a private/unavailable video.
error_rate_limited.json — yt-dlp stderr output for HTTP 429.
audio_sample.opus — a 3-second real Opus audio file used to test stream proxy and range request handling.
empty_result.json — yt-dlp exits 0 but stdout is an empty JSON object {}. Used for garbage-in testing.
malformed_missing_id.json — yt-dlp exits 0 but the id field is absent from the result. Used to test graceful field-missing handling.
The mock subprocess wrapper reads the relevant fixture and returns it with the correct returncode, stdout, and stderr fields. Tests that need to simulate a slow download use asyncio.sleep injection.
2.2 MusicBrainz & Cover Art Archive Mock
HTTP calls are intercepted using pytest-httpx (respx). Responses are recorded from the real MusicBrainz API once and stored as fixture JSON. This is the VCR (video cassette recorder) pattern — record once, replay forever.
Fixture files stored at tests/fixtures/musicbrainz/:
artist_search_radiohead.json — MB artist search result for 'Radiohead'.
release_list_radiohead.json — MB release list for Radiohead artist MBID.
recording_search_creep.json — MB recording search for 'Creep'.
no_results.json — empty MB search response for niche/unknown artist.
coverart_ok.jpg — a 1x1 pixel JPEG used as a stand-in cover art response.
coverart_404.json — Cover Art Archive 404 response body.
malformed_wrong_types.json — MB response where numeric fields (e.g. score) are returned as strings. Used for garbage-in testing.
malformed_missing_fields.json — MB response missing the releases array entirely. Used to test graceful degradation.
The respx router is configured in a pytest fixture (conftest.py) at session scope so it is shared across all tests without re-registration.
2.3 Navidrome Subsonic API Mock
A lightweight FastAPI mock server is spun up in-process using pytest-asyncio and HTTPX's AsyncClient. It implements only the Subsonic endpoints Harmonia actually calls:
GET /rest/ping — returns { status: 'ok' }
GET /rest/search3 — returns a fixed set of 3 library tracks
GET /rest/startScan — returns { status: 'ok', scanStatus: { scanning: false } }
GET /rest/getAlbumList2, getArtists, getPlaylists — return minimal fixture data
The mock server records every request it receives. Tests can assert on call count and parameters after the fact (e.g. assert mock_navidrome.scan_called_once()).
2.4 File System Mock
All file system operations use pytest's tmp_path fixture. The backend's MUSIC_LIBRARY_PATH and RAW_PATH environment variables are overridden at test time to point to temporary directories that are cleaned up automatically after each test.
A conftest.py fixture (fs_layout) creates the expected directory structure inside tmp_path before each test:
@pytest.fixture
def fs_layout(tmp_path):
raw = tmp_path / 'raw'
library = tmp_path / 'library'
raw.mkdir()
library.mkdir()
return {'raw': raw, 'library': library, 'db': tmp_path / 'harmonia.db'}
2.5 WebSocket Mock
FastAPI's built-in TestClient supports WebSocket connections in-process via the websockets protocol. No external mock is needed — the real FastAPI app is mounted in the test process with mocked dependencies injected via FastAPI's dependency_overrides mechanism.
A helper utility ws_collect(client, url, n_events) connects to a WebSocket endpoint and collects n events before closing, returning them as a list. This makes WebSocket assertions read identically to HTTP assertions.
3. Unit Tests
Unit tests cover pure functions and class methods in complete isolation. No I/O, no network, no database. Every test is a single function that runs in under 2 ms.
3.1 Backend Unit Tests (pytest)
3.1.1 Authentication (tests/unit/test_auth.py)

| Test name                          | Asserts                                                                            |
| ---------------------------------- | ---------------------------------------------------------------------------------- |
| test_password_hashed_with_bcrypt   | hash_password() produces a bcrypt hash; plain text is not stored                   |
| test_password_verify_correct       | verify_password(plain, hash) returns True for correct password                     |
| test_password_verify_wrong         | verify_password(plain, hash) returns False for wrong password                      |
| test_jwt_encode_decode_roundtrip   | encode_jwt() → decode_jwt() returns the same payload                               |
| test_jwt_expired_raises            | decode_jwt() raises ExpiredSignatureError for a token with past exp                |
| test_jwt_wrong_secret_raises       | decode_jwt() raises InvalidSignatureError for token signed with a different secret |
| test_stream_token_encode_decode    | stream token roundtrip preserves job_id and is scoped correctly                    |
| test_stream_token_expired_raises   | stream token with past expiry raises TokenExpiredError                             |
| test_stream_token_wrong_job_raises | stream token for job_id A cannot be used for job_id B                              |

3.1.2 Metadata Tagging (tests/unit/test_tagging.py)

| Test name                                | Asserts                                                                            |
| ---------------------------------------- | ---------------------------------------------------------------------------------- |
| test_tag_payload_valid_full              | TagPayload with all fields passes Pydantic validation                              |
| test_tag_payload_minimal                 | TagPayload with only title+artist is valid; optional fields default to None        |
| test_tag_payload_empty_title_invalid     | TagPayload with empty string title raises ValidationError                          |
| test_build_file_path_standard            | build_library_path(artist, album, year, track, title) returns correct path         |
| test_build_file_path_sanitises_slashes   | Artist/album names containing '/' are sanitised to '-'                             |
| test_build_file_path_no_year             | Omitting year produces <Artist>/<Album>/<Track> - <Title>.opus                     |
| test_beets_candidate_confidence_ordering | sort_candidates() returns list ordered highest confidence first                    |
| test_mutagen_write_id3_fields            | write_tags(file, payload) writes correct ID3 frames; read back with mutagen.File() |
| test_mutagen_write_opus_fields           | write_tags() on an Opus file writes correct Vorbis comment tags                    |

3.1.3 Proxy Header Sanitisation (tests/unit/test_proxy.py)

| Test name                   | Asserts                                                                    |
| --------------------------- | -------------------------------------------------------------------------- |
| test_referer_stripped       | sanitise_headers() removes Referer from outbound request headers           |
| test_forwarded_for_stripped | sanitise_headers() removes X-Forwarded-For and X-Real-IP                   |
| test_user_agent_replaced    | sanitise_headers() replaces User-Agent with the controlled Harmonia string |
| test_auth_header_stripped   | sanitise_headers() removes Authorization and Cookie headers                |
| test_safe_headers_preserved | Accept and Accept-Language headers are preserved unchanged                 |

3.1.4 Custom Metadata Store FTS5 (tests/unit/test_fts.py)

| Test name                             | Asserts                                                             |
| ------------------------------------- | ------------------------------------------------------------------- |
| test_fts_exact_match                  | FTS5 query for exact title returns that entry at top of results     |
| test_fts_fuzzy_partial_match          | Query for partial title substring returns correct entry             |
| test_fts_no_match_returns_empty       | Query for completely unrelated string returns empty list            |
| test_fts_insert_triggers_index_update | After INSERT into custom_tracks, the new entry is findable via FTS5 |
| test_fts_source_field_tagged_custom   | Suggestions from custom store have source='custom' in response      |

3.2 Frontend Unit Tests (Vitest)
Frontend unit tests cover utility functions, hooks logic (with mocked state), and Pydantic-equivalent Zod schema validation.
3.2.1 Subsonic Client (tests/unit/subsonic.test.ts)

| Test name                       | Asserts                                                              |
| ------------------------------- | -------------------------------------------------------------------- |
| builds correct auth params      | buildAuthParams() produces correct token+salt hash per Subsonic spec |
| parses search3 response         | parseSearch3() maps raw XML/JSON to typed SearchResult[]             |
| handles subsonic error code 40  | Subsonic error code 40 (wrong credentials) throws AuthError          |
| stream url includes token param | buildStreamUrl() appends ?token= for acquisition streams             |

3.2.2 Player Store (tests/unit/player.test.ts)

| Test name                                | Asserts                                                                                                           |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| play sets current track                  | play(track) updates store.currentTrack and sets isPlaying=true                                                    |
| pause clears isPlaying                   | pause() sets isPlaying=false without clearing currentTrack                                                        |
| next advances queue                      | next() on a 3-track queue advances to track 2                                                                     |
| next on last track with repeat-all wraps | next() on last track with repeat=all returns to track 1                                                           |
| shuffle produces different order         | enableShuffle() reorders queue; original order is preserved for unshuffle                                         |
| source switch does not interrupt         | switchSource() updates src without resetting currentTime                                                          |
| media session cleared on track end       | When audio fires 'ended' event, navigator.mediaSession.metadata is set to null — no ghost controls on lock screen |
| media session cleared on unmount         | usePlayer hook cleanup function sets navigator.mediaSession.metadata to null and removes all action handlers      |
| media session not cleared on pause       | pause() does not clear mediaSession.metadata — lock screen still shows the track while paused                     |

3.2.3 Request ID Middleware (tests/unit/requestId.test.ts)

| Test name                                   | Asserts                                                                                                |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| injects X-Request-ID on every fetch         | Middleware wraps global fetch; every outbound request carries X-Request-ID header with a valid UUID v4 |
| generates unique id per request             | Two sequential fetches carry different X-Request-ID values                                             |
| preserves existing request_id if present    | If caller explicitly sets X-Request-ID, middleware does not overwrite it                               |
| request_id forwarded to client error report | Error boundary capture includes the request_id of the fetch that was in-flight when the error occurred |

4. Integration Tests
Integration tests exercise full API request/response cycles against a real SQLite database and real file system (via tmp_path). All five external dependencies are mocked as defined in Section 2. Tests run the actual FastAPI app via HTTPX's AsyncClient — no HTTP port is opened.
4.1 Authentication Endpoints (tests/integration/test_auth_api.py)

| Test name                                  | Scenario                                                                                                             |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| test_setup_first_run                       | POST /api/auth/setup on empty DB returns 200, sets httpOnly cookie, GET /api/auth/status now returns configured:true |
| test_setup_already_configured              | POST /api/auth/setup when already configured returns 409 Conflict                                                    |
| test_login_correct_credentials             | POST /api/auth/login with correct creds returns 200 and sets JWT cookie                                              |
| test_login_wrong_password                  | POST /api/auth/login with wrong password returns 401                                                                 |
| test_protected_route_no_cookie             | GET /api/jobs/pending without cookie returns 401                                                                     |
| test_protected_route_with_cookie           | GET /api/jobs/pending with valid JWT cookie returns 200                                                              |
| test_protected_route_expired_cookie        | GET /api/jobs/pending with expired JWT returns 401                                                                   |
| test_logout_clears_cookie                  | POST /api/auth/logout sets cookie with max-age=0; subsequent protected request returns 401                           |
| test_request_id_present_in_response_header | Every authenticated response includes X-Request-ID header echoing the inbound value                                  |
| test_request_id_generated_if_absent        | Request with no X-Request-ID header → backend generates one; response header contains a valid UUID                   |

4.2 Search Endpoint (tests/integration/test_search_api.py)

| Test name                                | Scenario                                                                                            |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------- |
| test_search_query_returns_results_via_ws | POST /api/search {query:'Radiohead'} → WebSocket pushes 5 search_result events then search_complete |
| test_search_youtube_url_direct           | POST /api/search {url:'https://youtube.com/watch?v=...'} → single search_result pushed immediately  |
| test_search_flat_playlist_used           | yt-dlp mock asserts --flat-playlist flag was present in the subprocess call args                    |
| test_search_ytdlp_error_pushes_job_error | yt-dlp returns non-zero exit code → WebSocket pushes job_error event                                |
| test_search_result_schema_valid          | Every search_result event payload validates against SearchResult Pydantic model                     |

4.3 Acquisition & Stream Endpoints (tests/integration/test_acquire_api.py)

| Test name                                  | Scenario                                                                                                                                                |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| test_acquire_creates_job                   | POST /api/acquire returns {job_id, stream_token}; raw/<job_id>/job.json created on disk                                                                 |
| test_stream_valid_token                    | GET /api/stream/<job_id>?token=<valid> returns 200 with audio/ogg content-type                                                                          |
| test_stream_invalid_token_401              | GET /api/stream/<job_id>?token=<wrong> returns 401                                                                                                      |
| test_stream_expired_token_401              | GET /api/stream/<job_id>?token=<expired> returns 401                                                                                                    |
| test_stream_range_request                  | GET /api/stream with Range: bytes=0-1023 returns 206 Partial Content with correct byte range                                                            |
| test_ws_download_progress_events           | WebSocket receives download_progress events with percent 0→100 during mocked download                                                                   |
| test_ws_download_complete_event            | WebSocket receives download_complete after yt-dlp mock completes                                                                                        |
| test_ws_tagging_suggestions_pushed         | After download_complete, WebSocket receives tagging_suggestions with beets mock candidates                                                              |
| test_ytdlp_empty_json_zero_exit_handled    | yt-dlp exits 0 but returns {} — backend does not crash; job_error event pushed with recoverable: false                                                  |
| test_ytdlp_missing_id_field_handled        | yt-dlp result missing 'id' field — parser raises ParseError; job_error pushed with descriptive message                                                  |
| test_library_ready_delayed_frontend_stable | library_ready WS event delayed 15 seconds (asyncio.sleep mock) — GET /api/jobs/:job_id keeps returning status='pending'; no timeout crash or null state |

4.4 Tagging & Library Pipeline (tests/integration/test_tagging_api.py)

| Test name                                 | Scenario                                                                                                                                                                                                  |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| test_patch_tags_writes_file               | PATCH /api/acquire/<job_id>/tags → Mutagen reads back correct tags from the moved file                                                                                                                    |
| test_patch_tags_moves_to_library          | After PATCH, file exists at library/<Artist>/<Album>/<Track> - <Title>.opus; raw/<job_id>/ is empty                                                                                                       |
| test_patch_tags_triggers_navidrome_scan   | After PATCH, mock Navidrome asserts POST /rest/startScan was called exactly once with admin credentials                                                                                                   |
| test_library_ready_event_pushed           | After PATCH, WebSocket receives library_ready event                                                                                                                                                       |
| test_patch_tags_slash_in_artist_sanitised | Artist name containing '/' creates correct sanitised directory name                                                                                                                                       |
| test_patch_tags_stores_in_custom_db       | Confirmed tags are written to custom_tracks table for future suggestions                                                                                                                                  |
| test_job_recovered_after_restart          | Job created → backend process simulated restart (app re-instantiated with same tmp_path) → GET /api/jobs/:job_id returns correct status from job.json on disk; manual tag edits in job.json are preserved |
| test_job_recovery_no_orphan_files         | After restart recovery, no duplicate raw/ folders are created on re-acquire of the same job_id                                                                                                            |

4.5 Metadata Proxy Endpoints (tests/integration/test_metadata_api.py)

| Test name                                     | Scenario                                                                                                                              |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| test_mb_search_proxied                        | GET /api/metadata/search?type=artist&query=Radiohead returns fixture data; respx asserts outbound call was made to MusicBrainz        |
| test_mb_no_referer_forwarded                  | respx asserts outbound MusicBrainz request has no Referer header                                                                      |
| test_mb_user_agent_is_harmonia                | respx asserts outbound User-Agent starts with 'Harmonia/'                                                                             |
| test_coverart_proxied_returns_image           | GET /api/metadata/coverart/<mbid> returns image/jpeg content-type                                                                     |
| test_coverart_404_returns_404                 | Cover Art Archive 404 fixture → /api/metadata/coverart returns 404                                                                    |
| test_metadata_frontend_never_hits_mb_directly | Vitest: all metadata calls in useAcquisition hook target /api/metadata/*, never musicbrainz.org                                       |
| test_mb_wrong_types_returns_empty_candidates  | MB returns malformed_wrong_types.json fixture (numeric fields as strings) — proxy returns 200 with empty candidates[], does not crash |
| test_mb_missing_releases_field_handled        | MB returns malformed_missing_fields.json with no releases array — proxy returns empty candidates[], logs a WARNING                    |

5. Contract Tests
Contract tests verify that the public API shapes Harmonia depends on and exposes are exactly correct. They are the guard against silent interface drift — a plugin that changes its SearchResult schema, or a Navidrome response that drops a field.
5.1 Plugin API Contract (tests/contract/test_plugin_contract.py)
Every registered plugin is tested against the Plugin Contract defined in Section 5 of the Architecture spec. The test is parameterised over all installed plugins.
test_plugin_manifest_schema — plugin manifest JSON validates against the PluginManifest Pydantic model (id, name, version, base_url, capabilities, search_input, audio_formats, icon all present and correctly typed).
test_plugin_search_result_schema — every item returned by POST /api/search validates against the SearchResult Pydantic model. Run against the yt-dlp fixture response.
test_plugin_tag_payload_schema — TagPayload submitted to PATCH /api/acquire/:job_id/tags validates against the TagPayload Pydantic model. All required fields present, all optional fields nullable.
test_plugin_websocket_events_schema — every WebSocket event emitted during a mocked acquisition validates against its event schema (download_progress, download_complete, tagging_suggestions, library_ready, job_error).
5.2 Subsonic API Contract (tests/contract/test_subsonic_contract.py)
The mock Navidrome server is verified to return responses that match the OpenSubsonic spec. This catches cases where the mock drifts from reality.
test_ping_response_shape — GET /rest/ping returns { subsonic-response: { status: 'ok', version: string } }.
test_search3_response_shape — GET /rest/search3 returns well-formed SearchResult3 with song/album/artist arrays.
test_scan_status_shape — GET /rest/getScanStatus returns { scanStatus: { scanning: bool, count: number } }.
5.3 Internal API Contract (tests/contract/test_internal_contract.py)
Verifies the acquisition backend's own REST responses match the TypeScript types the frontend consumes. Types are defined in frontend/src/lib/types.ts and mirrored as Pydantic models in backend/schemas.py. Any drift between the two is a contract failure.
test_acquire_response_has_stream_token — POST /api/acquire response contains job_id (string) and stream_token (string).
test_job_status_shape — GET /api/jobs/:job_id response matches JobStatus schema (job_id, status enum, percent, error_message nullable).
test_search_result_thumbnail_is_relative — SearchResult thumbnail_url is a backend-relative path (/api/proxy/thumbnail/...), never an absolute external URL.
6. End-to-End Tests (Playwright)
E2E tests run the full stack — Next.js frontend, FastAPI backend, mock Navidrome, mock yt-dlp — in a Docker Compose test environment. Playwright drives a real browser. Tests run on Chromium (desktop), WebKit (iOS Safari simulation), and Mobile Chrome (Android simulation).
6.1 E2E Environment
docker-compose.test.yml spins up: harmonia-backend (with all mocks injected via environment flags), harmonia-frontend (pointing at test backend), mock-navidrome (the FastAPI mock from Section 2.3).
Playwright config sets baseURL to http://localhost:3000.
A global setup script (playwright/global-setup.ts) calls POST /api/auth/setup to create test credentials before any test runs.
A global teardown script wipes the test SQLite DB and tmp_path directories.
6.2 Authentication Flows (e2e/auth.spec.ts)

| Test name                        | User flow                                                                               |
| -------------------------------- | --------------------------------------------------------------------------------------- |
| first run shows setup screen     | Fresh DB → navigate to / → redirected to /setup → fill form → submit → land on main app |
| login with correct credentials   | Navigate to / → redirected to /login → fill credentials → submit → land on main app     |
| login wrong password shows error | Submit wrong password → error message visible → still on /login                         |
| logged in user not redirected    | After login, navigate to / directly → main app loads without redirect                   |
| logout clears session            | Click logout → redirected to /login → navigating to / redirects to /login again         |

6.3 Search & Acquisition Flow (e2e/acquisition.spec.ts)

| Test name                           | User flow                                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| search shows streamed results       | Open search → type 'Radiohead' → library results appear immediately → YouTube results stream in one by one |
| selecting result starts playback    | Click a YouTube result → mini player bar appears → audio element src is /api/stream/...                    |
| tagging panel appears during stream | 3 seconds after playback starts → tagging panel slides in → fields pre-filled with fixture beets data      |
| confidence badges visible           | Tagging panel shows confidence badge on each field; overall bar shows correct colour                       |
| mb fuzzy search populates field     | Type in Artist field → dropdown appears with MB fixture results → selecting one populates Album field      |
| confirm tags moves song to library  | Click Confirm → tagging panel closes → toast appears → library refreshes → song visible in Albums view     |
| pending tray shows unconfirmed jobs | Dismiss tagging panel → pending tray icon shows badge → tap it → job listed → tap to reopen panel          |

6.4 Player Flows (e2e/player.spec.ts)

| Test name                                   | User flow                                                                                                                                                                                                  |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| play from library                           | Navigate to Albums → tap album → tap track → mini player appears, isPlaying=true                                                                                                                           |
| full player opens on tap                    | Tap mini player bar → full player sheet opens with correct track info and cover art                                                                                                                        |
| queue reorder                               | Open queue → drag track 3 to position 1 → queue reflects new order                                                                                                                                         |
| media session integration                   | Playwright asserts navigator.mediaSession.metadata.title matches current track title                                                                                                                       |
| source switch is seamless                   | During stream playback, fire library_ready WS event → audio src changes → currentTime is preserved                                                                                                         |
| delayed library_ready does not crash player | Stream plays for 20s with no library_ready event → player stays in streaming state with indicator visible → library_ready fires late → source switches cleanly with no blank-out or error boundary trigger |
| deleted track purged from PWA cache         | Play and cache a track → delete it from Navidrome mock → reload app → service worker sync removes the track from cache → it no longer appears in offline library or plays from cache                       |

6.5 Cross-Browser Matrix
Every E2E test runs on all three browser configurations in CI:

| Browser       | Device emulation    | Tests                                               |
| ------------- | ------------------- | --------------------------------------------------- |
| Chromium      | Desktop 1280x800    | Full suite                                          |
| WebKit        | iPhone 14 (390x844) | Full suite — validates iOS Safari PWA behaviour     |
| Mobile Chrome | Pixel 7 (412x915)   | Full suite — validates Android Chrome PWA behaviour |

7. Logging
Harmonia uses structured logging throughout. The rule is simple: every log line must be enough to reconstruct what happened without a debugger. Log lines that say only 'error occurred' or 'request failed' are forbidden.
7.1 Backend Logging Stack
The Python backend uses structlog with two renderers:
Production (LOG_FORMAT=json): structlog JSONRenderer. Every line is a single JSON object on stdout. Compatible with Loki, Datadog, CloudWatch, and any log aggregator.
Development (LOG_FORMAT=pretty or unset): structlog ConsoleRenderer with colour coding. Readable in a terminal without parsing.
The log level is controlled by the LOG_LEVEL environment variable (default: INFO). DEBUG emits every yt-dlp subprocess argument, every outbound proxy request, and every WebSocket event. Production should stay at INFO.
7.2 Mandatory Log Fields
Every log line — regardless of level — must include:

| Field      | Type         | Example                                                                       |
| ---------- | ------------ | ----------------------------------------------------------------------------- |
| timestamp  | ISO 8601 UTC | 2026-03-15T14:22:01.341Z                                                      |
| level      | string       | info | warning | error | debug                                                |
| event      | string       | Human-readable summary of what happened                                       |
| service    | string       | harmonia-backend | harmonia-frontend                                          |
| module     | string       | acquisition | tagging | proxy | auth | search                                 |
| request_id | UUID string  | a3f2c1d0-... — present on all lines in a request lifecycle. See Section 7.2a. |

Additionally, log lines in the context of a job must include job_id. Log lines for HTTP requests must include method, path, status_code, and duration_ms.
7.2a Request Tracing (request_id / trace_id)
A request_id is a UUID generated per user action and threaded through every log line for that action's full lifecycle — spanning HTTP requests, WebSocket events, and background tasks. This makes it possible to reconstruct the complete story of any action from logs alone.
Implementation:
Frontend middleware (Next.js middleware.ts): generates a UUID v4 on every outbound fetch to the acquisition backend and attaches it as X-Request-ID header.
Backend middleware (FastAPI): reads X-Request-ID from incoming request headers (or generates one if absent). Binds it to the structlog context for the duration of the request using structlog.contextvars.bind_contextvars(request_id=...). All log lines emitted during that request automatically include it.
WebSocket connections: the request_id is passed as a query parameter when opening the WebSocket (ws://.../ws/<job_id>?request_id=...) and bound to the structlog context for the lifetime of that connection.
Background tasks: when a background task (beets import, file move, Navidrome rescan) is spawned from a request, the request_id is explicitly passed to the task function and rebound in that task's context.
With this in place, a single grep request_id=a3f2c1d0 in the logs returns every log line — HTTP, WebSocket, background — for that entire user action, in chronological order.
7.3 Logged Events by Module
7.3.1 Auth Module
INFO  — first_run_setup_complete { username }
INFO  — login_success { username, ip }
WARNING — login_failed { username, ip, reason: 'wrong_password' | 'user_not_found' }
WARNING — jwt_validation_failed { reason: 'expired' | 'invalid_signature' | 'malformed', path }
INFO  — logout { username }
7.3.2 Search Module
INFO  — search_started { search_id, query, source: 'query' | 'url' }
DEBUG — ytdlp_subprocess_args { search_id, args: [...] }
INFO  — search_result_pushed { search_id, result_count, duration_ms }
ERROR — search_failed { search_id, ytdlp_exit_code, stderr }
7.3.3 Acquisition Module
INFO  — job_created { job_id, youtube_id, title_hint }
DEBUG — ytdlp_download_args { job_id, args: [...] }
INFO  — download_progress { job_id, percent, speed, eta }
INFO  — download_complete { job_id, file_path, duration_ms }
ERROR — download_failed { job_id, ytdlp_exit_code, stderr }
INFO  — stream_token_issued { job_id, expires_at }
WARNING — stream_token_rejected { job_id, reason: 'expired' | 'wrong_job' | 'invalid_signature' }
7.3.4 Tagging Module
INFO  — beets_import_started { job_id, file_path }
INFO  — beets_suggestions_ready { job_id, candidate_count, top_confidence }
WARNING — beets_no_match { job_id, file_path } — falls back to manual entry
INFO  — tags_confirmed { job_id, title, artist, album, mb_recording_id }
INFO  — file_moved_to_library { job_id, source_path, dest_path }
ERROR — file_move_failed { job_id, source_path, dest_path, error }
INFO  — navidrome_scan_triggered { job_id, navidrome_url }
WARNING — navidrome_scan_failed { job_id, status_code, response_body }
7.3.5 Proxy Module
DEBUG — proxy_request_outbound { target: 'musicbrainz' | 'coverart', url, headers_sent }
DEBUG — proxy_response_received { target, status_code, duration_ms }
WARNING — proxy_upstream_error { target, status_code, url }
ERROR — proxy_request_failed { target, url, error }
7.3.6 System Module
INFO  — ytdlp_update_check_started { current_version }
INFO  — ytdlp_update_complete { old_version, new_version }
INFO  — ytdlp_already_up_to_date { version }
ERROR — ytdlp_update_failed { error }
INFO  — gc_worker_started { max_age_hours }
INFO  — gc_job_deleted { job_id, raw_path, age_hours, freed_bytes }
WARNING — gc_delete_failed { job_id, raw_path, error }
INFO  — gc_worker_complete { deleted_count, freed_bytes_total, duration_ms }
7.3.7 Metrics Module
INFO  — metric_search_duration { search_id, duration_ms, result_count, source: 'ytdlp' }
INFO  — metric_download_duration { job_id, duration_ms, file_size_bytes, audio_format }
INFO  — metric_tagging_duration { job_id, duration_ms, beets_confidence, source: 'beets' | 'musicbrainz' | 'custom' | 'manual' }
INFO  — metric_file_move_duration { job_id, duration_ms }
INFO  — metric_navidrome_scan_duration { job_id, duration_ms, status_code }
These events are emitted alongside normal log output. The GET /api/system/metrics endpoint aggregates them from the last 24 hours and returns a JSON summary — no external Prometheus server required.
7.4 Frontend Logging
The Next.js frontend logs to the browser console in development. In production, unhandled JS errors and React Error Boundary captures are sent to POST /api/logs/client on the acquisition backend, where they are logged as structured JSON alongside server logs. This means all errors — client and server — appear in one place and carry the same request_id.
Client error payload (POST /api/logs/client body):
{
"request_id": string,   // the X-Request-ID for the failed action
"error": string,        // error message
"stack": string,        // stack trace
"component": string,    // React component name if from Error Boundary
"route": string,        // current Next.js route
"user_agent": string,
"timestamp": string     // ISO 8601 UTC
}
WebSocket disconnects and reconnection attempts are logged at WARN level with job_id, request_id, and disconnect reason.
Subsonic API errors are logged with the Subsonic error code and message, not just the HTTP status.
The /api/logs/client endpoint is rate-limited to 10 requests per minute to prevent a crash loop from flooding logs.
7.5 What Is Deliberately Not Logged
The following are never written to logs under any circumstances:
Passwords or password hashes — not even partially or truncated.
JWT tokens or stream tokens — log the job_id or username instead.
Full file paths containing the user's real name if the library is under /home/<user>/ — log relative paths from MUSIC_LIBRARY_PATH.
Full MusicBrainz query strings that contain song titles — these could be used to reconstruct listening habits. Log the query type and result count only at INFO; full query only at DEBUG.
7.6 Metrics Endpoint (GET /api/system/metrics)
The metrics endpoint returns a JSON summary of the last 24 hours of operation, aggregated from the metrics log events defined in Section 7.3.7. No external Prometheus server or time-series database is required — the backend aggregates from its own structured log buffer in memory, with a rolling 24-hour window.
Response shape:
{
"search": {
"count": number,
"avg_duration_ms": number,
"p95_duration_ms": number
},
"download": {
"count": number,
"avg_duration_ms": number,
"total_bytes": number
},
"tagging": {
"count": number,
"avg_beets_confidence": number,
"source_breakdown": { beets: n, musicbrainz: n, custom: n, manual: n }
},
"ytdlp_version": string,
"gc_last_run": string,         // ISO 8601
"raw_folder_size_bytes": number
}
7.7 PWA Cache Invalidation Strategy
The service worker caches the last 50 played tracks from Navidrome for offline playback. Without a purge strategy, a deleted track would remain playable from cache and continue appearing in the offline library indefinitely.
Strategy: on every app open (service worker 'activate' and page focus events), the frontend runs a cache validation pass:
Fetch the current library track IDs from Navidrome via GET /rest/getStarred2 and a lightweight GET /rest/getAlbumList2 (recently added, max 50).
Compare against the set of track IDs in the service worker cache.
Any cached track whose ID is not present in the current Navidrome library is deleted from the cache.
This runs asynchronously in the background — it does not block app startup or playback.
Integration test: test_pwa_cache_purge_on_deleted_track — mock Navidrome returns a library missing track ID X → cache validation pass runs → track X is no longer in service worker cache.
7.8 Raw Folder Garbage Collection Worker
The /data/raw/ folder stores in-progress and completed downloads awaiting tag confirmation. Without cleanup, unconfirmed jobs accumulate indefinitely. A background APScheduler worker runs every 6 hours and deletes any raw/<job_id>/ folder whose job.json has a created_at timestamp older than 48 hours and a status that is not 'confirmed'.
The age threshold is configurable via the GC_RAW_MAX_AGE_HOURS environment variable (default: 48).
Before deleting, the worker logs gc_job_deleted with job_id, age, and freed_bytes.
A job whose tagging panel is actively open (status='tagging_in_progress') is skipped regardless of age — the user is mid-action.
Integration test: test_gc_deletes_stale_raw_folder — create a job with a backdated created_at → run GC worker → assert raw/<job_id>/ is gone and gc_job_deleted was logged.
Integration test: test_gc_skips_active_tagging_job — job with status='tagging_in_progress' and age > 48h → GC worker skips it → folder still exists.
8. CI Pipeline (GitHub Actions)
Tests run automatically on every push and pull request. The pipeline is defined in .github/workflows/ci.yml and consists of three jobs that run in parallel after a shared setup step.
8.1 Pipeline Structure
on: [push, pull_request]
jobs:
backend-tests:
runs-on: ubuntu-latest
steps:
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
with: { python-version: '3.12' }
- run: pip install -r backend/requirements-dev.txt
- run: pytest backend/tests/ -v --cov=backend --cov-report=xml
- uses: codecov/codecov-action@v4
frontend-tests:
runs-on: ubuntu-latest
steps:
- uses: actions/checkout@v4
- uses: actions/setup-node@v4
with: { node-version: '20' }
- run: cd frontend && npm ci
- run: cd frontend && npx vitest run --coverage
e2e-tests:
runs-on: ubuntu-latest
steps:
- uses: actions/checkout@v4
- uses: actions/setup-node@v4
with: { node-version: '20' }
- run: cd frontend && npm ci
- run: npx playwright install --with-deps chromium webkit
- run: docker compose -f docker-compose.test.yml up -d
- run: cd frontend && npx playwright test
- uses: actions/upload-artifact@v4
if: failure()
with:
name: playwright-report
path: frontend/playwright-report/
8.2 Coverage Requirements
The CI pipeline fails if coverage drops below the following thresholds:

| Area                            | Minimum coverage | Rationale                                                |
| ------------------------------- | ---------------- | -------------------------------------------------------- |
| backend/auth                    | 100%             | Security code has no acceptable untested paths           |
| backend/tagging                 | 95%              | File move and tag writing are high-risk operations       |
| backend/proxy                   | 100%             | Header sanitisation must be exhaustively verified        |
| backend/acquisition             | 90%              | Core pipeline logic                                      |
| backend/middleware (request_id) | 100%             | Tracing middleware must never silently drop a request_id |
| backend/gc_worker               | 90%              | Deletion logic; skip-active-job path must be covered     |
| backend/metrics                 | 85%              | Aggregation logic for /api/system/metrics                |
| frontend/lib                    | 90%              | Subsonic client, auth utils, request_id injection        |
| frontend/store                  | 85%              | Player and queue state logic, Media Session cleanup      |

8.3 Failure Behaviour
Any unit or integration test failure blocks merge. No exceptions.
Any contract test failure blocks merge. A contract failure means an interface has changed and the other side has not been updated — it must be resolved before merging.
E2E failures on Chromium block merge. E2E failures on WebKit or Mobile Chrome produce a warning but do not block merge — they are tracked as known platform issues and resolved in the same sprint.
Coverage below threshold blocks merge.
On failure, Playwright HTML report is uploaded as a CI artifact. It contains screenshots and traces for every failed test step.
9. Test File Layout
backend/
tests/
conftest.py              # shared fixtures: fs_layout, mock_navidrome, respx_router
fixtures/
ytdlp/
search_flat.json
download_complete.json
error_private_video.json
error_rate_limited.json
audio_sample.opus
empty_result.json             # garbage-in: exit 0, empty {}
malformed_missing_id.json      # garbage-in: exit 0, no 'id' field
musicbrainz/
artist_search_radiohead.json
release_list_radiohead.json
recording_search_creep.json
no_results.json
coverart_ok.jpg
coverart_404.json
malformed_wrong_types.json     # garbage-in: numeric fields as strings
malformed_missing_fields.json  # garbage-in: releases array absent
unit/
test_auth.py
test_tagging.py
test_proxy.py
test_fts.py
integration/
test_auth_api.py
test_search_api.py
test_acquire_api.py
test_tagging_api.py
test_metadata_api.py
test_gc_worker.py              # GC worker and raw/ cleanup
test_job_recovery.py           # backend restart / job state persistence
test_metrics_api.py            # /api/system/metrics endpoint
test_client_logs_api.py        # /api/logs/client endpoint
contract/
test_plugin_contract.py
test_subsonic_contract.py
test_internal_contract.py
frontend/
tests/
unit/
subsonic.test.ts
player.test.ts             # includes Media Session cleanup tests
requestId.test.ts          # X-Request-ID header injection middleware
e2e/
auth.spec.ts
acquisition.spec.ts         # includes delayed library_ready race test
player.spec.ts              # includes PWA cache invalidation test
playwright.config.ts
global-setup.ts
global-teardown.ts
.github/
workflows/
ci.yml
End of Testing & Observability Specification  ·  Harmonia v1.1  ·  Observability, resilience & safeguards hardening