# Harmonia — Claude Code Project Context

## What this project is
Harmonia is a self-hosted music platform that merges Navidrome (library streaming) with a
YouTube acquisition pipeline into a single cohesive app. Backend is Python/FastAPI, frontend
is Next.js 15 + TypeScript + Tailwind.

Key principles: one interface, instant gratification (stream while downloading), permanent
ownership (properly tagged local library), privacy by default (all external calls proxied),
extensibility (plugin contract for new source backends).

## Spec documents — read these before implementing any file
- `docs/Harmonia_Architecture.md` — complete architecture, API contracts, DB schema, ADRs
- `docs/Harmonia_Testing_Observability.md` — test spec, fixture strategy, coverage requirements

## Reference files — read before writing anything in that domain
- `backend/routers/auth.py` — read before writing ANY router (establishes all patterns)
- `backend/tests/conftest.py` — read before writing ANY test (all fixtures defined here)
- `frontend/src/components/ui/GlassCard.tsx` — read before writing ANY component (8 patterns)

## Running the project

### Backend
```bash
source backend/.venv/bin/activate
cd backend && uvicorn backend.main:app --reload
```

### Frontend
```bash
cd frontend && npm run dev
```

### Docker Compose
```bash
docker-compose up   # ports: Navidrome 15000, backend 15001, frontend 15002
```

## Running tests
```bash
source backend/.venv/bin/activate

# Single file (most common during development)
cd backend && pytest tests/unit/test_job_store.py -v

# All unit tests
cd backend && pytest tests/unit/ -v

# Full suite with coverage
cd backend && pytest tests/ --cov=backend --cov-report=term-missing

# Frontend
cd frontend && npm run test
cd frontend && npm run test:coverage
cd frontend && npm run e2e
```

## Architecture layers
1. **Frontend** (Next.js + Tailwind + shadcn/ui) — PWA, Subsonic API client, plugin orchestration
2. **Navidrome** — library management, Subsonic API, transcoding
3. **Acquisition Backend** (FastAPI) — yt-dlp, streaming proxy, beets tagging, metadata proxy
4. **File System** — `/data/raw/` staging, `/data/library/` Navidrome root

## Key files
| File | Purpose |
|------|---------|
| `backend/schemas.py` | ALL Pydantic models — source of truth, never modify without updating types.ts |
| `backend/database.py` | AsyncDB class — always use `get_db()` dependency, never open connections directly |
| `backend/auth.py` | Pure auth functions — hash/verify password, encode/decode JWT + stream tokens |
| `backend/config.py` | Settings singleton — always `from backend.config import settings`, never `os.environ` |
| `backend/plugin_base.py` | SourcePlugin ABC + MockYouTubePlugin — reference for plugin implementations |
| `frontend/src/lib/types.ts` | ALL TypeScript types — must stay in sync with schemas.py |
| `frontend/tailwind.config.ts` | Design tokens — always use these, never hardcode colours |

## Non-negotiable backend conventions

**Routes:**
- Every route has explicit `response_model` and `status_code`
- No business logic in route functions — call a service, return its result
- All errors: `{"error": "machine_code", "detail": "human message", "request_id": "uuid"}`
- HTTP codes: 201 create · 204 no body · 400 business rule · 401 auth · 404 missing · 409 conflict · 422 validation · 429 rate limit · 502 upstream · 504 timeout

**Data:**
- All datetimes UTC ISO 8601: `YYYY-MM-DDTHH:MM:SSZ` — use `datetime.now(UTC)`, never `datetime.now()`
- All JSON responses camelCase — enforced by `_CamelModel` base class in schemas.py
- Job IDs: UUID v4 always

**Logging:**
- Always `log = logger.bind(...)` per-function — never use module logger directly in routes
- Every log line in a job context must include `job_id`
- Never log passwords, JWT tokens, stream tokens, or full MusicBrainz query strings

**Services:**
- Job state machine enforced in `job_store.py` — raise `StateTransitionError` for illegal transitions
- File path sanitisation: replace `/ \ : * ? " < > |` and leading `.` with `-`, max 200 chars

## Non-negotiable test conventions
- Never redefine a fixture — if it should exist, add it to `conftest.py`
- Use `ws_collect(client, url, n_events)` for all WebSocket assertions
- Use `auth_client` fixture for any protected route test
- Stable fixture names (never rename): `fs_layout`, `db`, `client`, `auth_client`, `mock_navidrome`, `respx_router`, `mock_ytdlp`
- Run the relevant test file after every implementation and fix all failures before finishing

## Non-negotiable frontend conventions
- All colours from `tailwind.config.ts` tokens — never hardcode hex values
- Glass surface: `backdrop-blur-glass bg-white/[.06] border border-white/[.08] rounded-card`
- Purple (`accent-*`) for interactive states, Gold (`gold-*`) for confidence scores and highlights
- Text hierarchy: `text-text-primary` → `text-text-secondary` → `text-text-tertiary`
- Import `cn()` from `@/lib/utils` for all className merging

## Implementation order — Phase 1 (do not skip ahead)
1. `backend/services/job_store.py` — no dependencies, everything else needs it
2. `backend/tests/unit/test_job_store.py` — write alongside implementation
3. `backend/tests/unit/test_auth.py` — auth.py already written, just needs tests
4. `backend/services/ytdlp.py` — yt-dlp subprocess wrapper
5. `backend/ws/job.py` — job WebSocket handler
6. `backend/ws/search.py` — search WebSocket handler
7. `backend/routers/acquire.py` — acquire/stream/jobs endpoints
8. `backend/routers/search.py` — search endpoint

## What NOT to do
- Never open a DB connection directly in a route — always `Depends(get_db)`
- Never call `os.environ` — always `from backend.config import settings`
- Never `datetime.now()` without UTC timezone
- Never hardcode colour values in frontend components
- Never modify `schemas.py` without also updating `frontend/src/lib/types.ts` AND `backend/tests/contract/test_schema_parity.py`
- Never run `npm audit fix --force` — breaks dependency resolution
- Never implement two files in one task — one file at a time, tests green before moving on
- Never redefine fixtures in a test file — add to `conftest.py` only

## Environment variables (all documented in `.env.example`)
Required: `JWT_SECRET`, `NAVIDROME_URL`, `NAVIDROME_ADMIN_USER/PASS`, `NAVIDROME_APP_USER/PASS`, `MUSICBRAINZ_CONTACT_URL`
Paths default to `/data/` subpaths: `MUSIC_LIBRARY_PATH`, `RAW_PATH`, `DB_PATH`
Logging: `LOG_FORMAT` (json/pretty), `LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR)