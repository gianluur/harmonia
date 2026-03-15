#!/usr/bin/env bash
# =============================================================================
# Harmonia — full project scaffold
#
# Usage:
#   chmod +x scaffold.sh
#   ./scaffold.sh
#
# What it does:
#   1. Creates the complete directory tree
#   2. Copies every pre-written file into its correct location
#   3. Creates empty placeholder files for everything still to be implemented
#      (each placeholder has a one-line comment saying what it should contain)
#   4. Creates all config files (pyproject.toml, .gitignore, Dockerfiles, etc.)
#   5. Initialises a git repo and makes an initial commit
#
# Prerequisites: bash, git, python3 (for the placeholder comment generation)
# Run from inside your ~/Documents/Projects/Harmonia folder.
# All files are created in-place — no subfolder is created.
# =============================================================================

set -euo pipefail

# Resolve the directory where this script lives (where your pre-written files are)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="."

echo "Scaffolding Harmonia in: $(pwd)"
echo ""

# =============================================================================
# 1. Create directory tree
# =============================================================================
mkdir -p "$PROJECT"/{backend/{routers,ws,services,workers,plugins,tests/{fixtures/{ytdlp,musicbrainz},unit,integration,contract}},frontend/src/{app/{setup,login},components/{player,library,search,tagging,ui},hooks,lib,store},".github/workflows"}

echo "✓ Directory tree created"

# =============================================================================
# 2. Copy pre-written files
# =============================================================================

# Backend core
[ "$SCRIPT_DIR/schemas.py" -ef "$PROJECT/backend/schemas.py" ] || cp "$SCRIPT_DIR/schemas.py" "$PROJECT/backend/schemas.py"
[ "$SCRIPT_DIR/database.py" -ef "$PROJECT/backend/database.py" ] || cp "$SCRIPT_DIR/database.py" "$PROJECT/backend/database.py"
[ "$SCRIPT_DIR/auth.py" -ef "$PROJECT/backend/auth.py" ] || cp "$SCRIPT_DIR/auth.py" "$PROJECT/backend/auth.py"
[ "$SCRIPT_DIR/config.py" -ef "$PROJECT/backend/config.py" ] || cp "$SCRIPT_DIR/config.py" "$PROJECT/backend/config.py"
[ "$SCRIPT_DIR/main.py" -ef "$PROJECT/backend/main.py" ] || cp "$SCRIPT_DIR/main.py" "$PROJECT/backend/main.py"
[ "$SCRIPT_DIR/middleware.py" -ef "$PROJECT/backend/middleware.py" ] || cp "$SCRIPT_DIR/middleware.py" "$PROJECT/backend/middleware.py"
[ "$SCRIPT_DIR/plugin_base.py" -ef "$PROJECT/backend/plugin_base.py" ] || cp "$SCRIPT_DIR/plugin_base.py" "$PROJECT/backend/plugin_base.py"

# Routers
[ "$SCRIPT_DIR/auth_router.py" -ef "$PROJECT/backend/routers/auth.py" ] || cp "$SCRIPT_DIR/auth_router.py" "$PROJECT/backend/routers/auth.py"

# Tests
[ "$SCRIPT_DIR/conftest.py" -ef "$PROJECT/backend/tests/conftest.py" ] || cp "$SCRIPT_DIR/conftest.py" "$PROJECT/backend/tests/conftest.py"
[ "$SCRIPT_DIR/test_schema_parity.py" -ef "$PROJECT/backend/tests/contract/test_schema_parity.py" ] || cp "$SCRIPT_DIR/test_schema_parity.py" "$PROJECT/backend/tests/contract/test_schema_parity.py"

# Frontend
[ "$SCRIPT_DIR/types.ts" -ef "$PROJECT/frontend/src/lib/types.ts" ] || cp "$SCRIPT_DIR/types.ts" "$PROJECT/frontend/src/lib/types.ts"
[ "$SCRIPT_DIR/GlassCard.tsx" -ef "$PROJECT/frontend/src/components/ui/GlassCard.tsx" ] || cp "$SCRIPT_DIR/GlassCard.tsx" "$PROJECT/frontend/src/components/ui/GlassCard.tsx"
[ "$SCRIPT_DIR/tailwind.config.ts" -ef "$PROJECT/frontend/tailwind.config.ts" ] || cp "$SCRIPT_DIR/tailwind.config.ts" "$PROJECT/frontend/tailwind.config.ts"
[ "$SCRIPT_DIR/package.json" -ef "$PROJECT/frontend/package.json" ] || cp "$SCRIPT_DIR/package.json" "$PROJECT/frontend/package.json"

# Deps
[ "$SCRIPT_DIR/requirements.txt" -ef "$PROJECT/backend/requirements.txt" ] || cp "$SCRIPT_DIR/requirements.txt" "$PROJECT/backend/requirements.txt"
[ "$SCRIPT_DIR/requirements-dev.txt" -ef "$PROJECT/backend/requirements-dev.txt" ] || cp "$SCRIPT_DIR/requirements-dev.txt" "$PROJECT/backend/requirements-dev.txt"
[ "$SCRIPT_DIR/.env.example" -ef "$PROJECT/.env.example" ] || cp "$SCRIPT_DIR/.env.example" "$PROJECT/.env.example"

echo "✓ Pre-written files copied"

# =============================================================================
# 3. Placeholder files — backend
# =============================================================================

placeholder() {
  local file="$1"
  local description="$2"
  # Only create if it doesn't already exist (pre-written files take priority)
  if [ ! -f "$file" ]; then
    echo "# $description" > "$file"
  fi
}

# Routers
placeholder "$PROJECT/backend/routers/__init__.py"   "Router package"
placeholder "$PROJECT/backend/routers/acquire.py"    "POST /api/acquire, GET /api/stream/:job_id, GET /api/jobs/:job_id, GET /api/jobs/pending, PATCH /api/acquire/:job_id/tags — see Architecture §4.1.2"
placeholder "$PROJECT/backend/routers/search.py"     "POST /api/search — initiates WS search session — see Architecture §4.1.2"
placeholder "$PROJECT/backend/routers/metadata.py"   "GET /api/metadata/search, GET /api/metadata/coverart/:mbid, GET /api/custom-metadata/suggest — see Architecture §4.1.3"
placeholder "$PROJECT/backend/routers/system.py"     "GET /api/system/status, GET /api/system/metrics, POST /api/system/update-ytdlp, POST /api/logs/client — see Architecture §4.1.4"

# WebSocket handlers
placeholder "$PROJECT/backend/ws/__init__.py"        "WebSocket handler package"
placeholder "$PROJECT/backend/ws/job.py"             "WebSocket handler for ws/<job_id> — job event fan-out, reconnection state recovery — see Architecture §4.2.1"
placeholder "$PROJECT/backend/ws/search.py"          "WebSocket handler for ws/search — accepts search messages, runs yt-dlp, streams results — see Architecture §4.2.2"

# Services
placeholder "$PROJECT/backend/services/__init__.py"  "Services package"
placeholder "$PROJECT/backend/services/job_store.py" "SQLite job CRUD: create_job(), get_job(), update_job_status(), list_pending_jobs() — enforces state machine — see Architecture §7.2"
placeholder "$PROJECT/backend/services/ytdlp.py"     "run_search() → AsyncGenerator[SearchResult], run_download() → AsyncGenerator[DownloadEvent] — thin yt-dlp subprocess wrapper — see Architecture §12.1"
placeholder "$PROJECT/backend/services/tagger.py"    "run_beets(), write_tags(), build_library_path(), sanitise_path_component() — see Architecture §12.1"
placeholder "$PROJECT/backend/services/custom_meta.py" "CustomMetadataStore: suggest(), save() — FTS5 trigram search — see Architecture §7"
placeholder "$PROJECT/backend/services/navidrome.py" "trigger_scan() — uses NAVIDROME_ADMIN_USER/PASS, returns navidrome_id — see Architecture §12.1"
placeholder "$PROJECT/backend/services/proxy.py"     "sanitise_headers(), search_musicbrainz(), get_coverart() — strips identifying headers per Architecture §9.1"
placeholder "$PROJECT/backend/services/metrics.py"   "Rolling 24h metrics buffer: record_*(), get_metrics() → SystemMetrics — thread-safe via asyncio.Lock — see Architecture §12.1"

# Workers
placeholder "$PROJECT/backend/workers/__init__.py"   "Workers package"
placeholder "$PROJECT/backend/workers/gc.py"         "APScheduler job: runs every 6h, deletes raw/<job_id>/ folders older than GC_RAW_MAX_AGE_HOURS — see Architecture §7.8 / Testing §7.8"
placeholder "$PROJECT/backend/workers/ytdlp_updater.py" "APScheduler job: runs every 24h, pip install -U yt-dlp — see Architecture §9.4"

# Plugins
placeholder "$PROJECT/backend/plugins/__init__.py"   "Plugin package"
placeholder "$PROJECT/backend/plugins/youtube.py"    "YouTubePlugin(SourcePlugin) — real yt-dlp implementation of plugin_base.SourcePlugin — see Architecture §5"
placeholder "$PROJECT/backend/plugins.py"            "PluginRegistry: load_plugins(), get_plugin(id) — validates manifests against PluginManifest schema — see Architecture §12.1"

# Backend package init
placeholder "$PROJECT/backend/__init__.py"           "Backend package"

# =============================================================================
# 4. Placeholder files — backend tests
# =============================================================================

placeholder "$PROJECT/backend/tests/__init__.py"                          "Tests package"
placeholder "$PROJECT/backend/tests/unit/__init__.py"                     "Unit tests package"
placeholder "$PROJECT/backend/tests/unit/test_auth.py"                    "Unit tests for backend/auth.py — see Testing spec §3.1.1"
placeholder "$PROJECT/backend/tests/unit/test_tagging.py"                 "Unit tests for backend/services/tagger.py — see Testing spec §3.1.2"
placeholder "$PROJECT/backend/tests/unit/test_proxy.py"                   "Unit tests for backend/services/proxy.py — see Testing spec §3.1.3"
placeholder "$PROJECT/backend/tests/unit/test_fts.py"                     "Unit tests for backend/services/custom_meta.py FTS5 — see Testing spec §3.1.4"
placeholder "$PROJECT/backend/tests/unit/test_gc_worker.py"               "Unit tests for backend/workers/gc.py — see Testing spec §3.1.5"
placeholder "$PROJECT/backend/tests/unit/test_metrics.py"                 "Unit tests for backend/services/metrics.py — see Testing spec §3.1.6"
placeholder "$PROJECT/backend/tests/unit/test_job_store.py"               "Unit tests for backend/services/job_store.py state machine — see Testing spec §3.1.7"
placeholder "$PROJECT/backend/tests/integration/__init__.py"              "Integration tests package"
placeholder "$PROJECT/backend/tests/integration/test_auth_api.py"        "Integration tests for /api/auth/* — see Testing spec §4.1"
placeholder "$PROJECT/backend/tests/integration/test_search_api.py"      "Integration tests for /api/search — see Testing spec §4.2"
placeholder "$PROJECT/backend/tests/integration/test_acquire_api.py"     "Integration tests for /api/acquire, /api/stream, /api/jobs — see Testing spec §4.3"
placeholder "$PROJECT/backend/tests/integration/test_tagging_api.py"     "Integration tests for PATCH /api/acquire/:id/tags pipeline — see Testing spec §4.4"
placeholder "$PROJECT/backend/tests/integration/test_metadata_api.py"    "Integration tests for /api/metadata/* proxy — see Testing spec §4.5"
placeholder "$PROJECT/backend/tests/integration/test_gc_worker.py"       "Integration tests for GC worker — see Testing spec §4.6"
placeholder "$PROJECT/backend/tests/integration/test_metrics_api.py"     "Integration tests for /api/system/metrics — see Testing spec §4.7"
placeholder "$PROJECT/backend/tests/integration/test_client_logs_api.py" "Integration tests for /api/logs/client — see Testing spec §4.8"
placeholder "$PROJECT/backend/tests/contract/__init__.py"                 "Contract tests package"
placeholder "$PROJECT/backend/tests/contract/test_plugin_contract.py"    "Contract tests for plugin API — see Testing spec §5.1"
placeholder "$PROJECT/backend/tests/contract/test_subsonic_contract.py"  "Contract tests for Subsonic API mock — see Testing spec §5.2"
placeholder "$PROJECT/backend/tests/contract/test_internal_contract.py"  "Contract tests for internal REST API shapes — see Testing spec §5.3"

# Fixture placeholder README files
cat > "$PROJECT/backend/tests/fixtures/ytdlp/README.md" << 'EOF'
# yt-dlp fixtures

Place the following files here before running tests:

| File | Description |
|------|-------------|
| `search_flat.json` | `--flat-playlist --dump-json` output for a 5-result search |
| `download_complete.json` | `--dump-json` output for a single video after full extraction |
| `error_private_video.json` | stderr for a private/unavailable video |
| `error_rate_limited.json` | stderr for HTTP 429 |
| `audio_sample.opus` | 3-second real Opus file for stream/range tests |
| `empty_result.json` | yt-dlp exits 0 but stdout is `{}` |
| `malformed_missing_id.json` | exits 0 but `id` field is absent |

Generate `audio_sample.opus` with:
  ffmpeg -f lavfi -i "sine=frequency=440:duration=3" -c:a libopus audio_sample.opus
EOF

cat > "$PROJECT/backend/tests/fixtures/musicbrainz/README.md" << 'EOF'
# MusicBrainz fixtures

Record these once from the real MB API, then commit them (VCR pattern).

| File | Description |
|------|-------------|
| `artist_search_radiohead.json` | MB artist search for 'Radiohead' |
| `release_list_radiohead.json` | MB release list for Radiohead MBID |
| `recording_search_creep.json` | MB recording search for 'Creep' |
| `no_results.json` | Empty MB response for unknown artist |
| `coverart_ok.jpg` | 1×1 pixel JPEG (stand-in cover art) |
| `coverart_404.json` | Cover Art Archive 404 body |
| `malformed_wrong_types.json` | Numeric fields returned as strings |
| `malformed_missing_fields.json` | releases array absent |

Record with:
  curl "https://musicbrainz.org/ws/2/artist?query=Radiohead&fmt=json" \
    -H "User-Agent: Harmonia/1.0 (dev)" > artist_search_radiohead.json
EOF

echo "✓ Backend placeholder files created"

# =============================================================================
# 5. Placeholder files — frontend
# =============================================================================

placeholder "$PROJECT/frontend/src/app/layout.tsx"           "Root layout: QueryClientProvider, Zustand providers, Inter font — see Architecture §6.1"
placeholder "$PROJECT/frontend/src/app/page.tsx"             "Library home: redirects to /setup or /login if needed — see Architecture §6.1"
placeholder "$PROJECT/frontend/src/app/setup/page.tsx"       "First-run setup form — see Architecture §11.1"
placeholder "$PROJECT/frontend/src/app/login/page.tsx"       "Login form — see Architecture §11.2"
placeholder "$PROJECT/frontend/src/lib/subsonic.ts"          "Subsonic API wrapper: buildAuthParams(), buildStreamUrl(), parseSearch3() — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/lib/acquisition.ts"       "Acquisition backend REST client: thin fetch wrappers + X-Request-ID injection — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/lib/plugins.ts"           "Plugin registry: dispatches search/acquire to correct plugin — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/lib/utils.ts"             "cn() helper (clsx + tailwind-merge) and other shared utilities"
placeholder "$PROJECT/frontend/src/middleware.ts"            "Next.js middleware: generates X-Request-ID UUID v4 per outbound fetch — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/store/player.ts"          "Zustand player store: currentTrack, isPlaying, volume, repeat, shuffle, Media Session API — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/store/queue.ts"           "Zustand queue store: tracks[], add(), remove(), reorder(), next(), previous() — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/hooks/usePlayer.ts"       "Audio element management: ties HTML5 <audio> to player store, library_ready source switch — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/hooks/useSubsonic.ts"     "TanStack Query hooks for all Subsonic endpoints — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/hooks/useAcquisition.ts"  "WebSocket management for job + search channels, reconnect logic — see Architecture §12.2"
placeholder "$PROJECT/frontend/src/components/player/MiniPlayer.tsx"  "Mini player bar: always visible once playing, sits above bottom nav on mobile — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/components/player/FullPlayer.tsx"  "Full screen player modal/sheet — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/components/player/Queue.tsx"       "Queue: drag-to-reorder, swipe-to-remove — see Architecture §6.3"
placeholder "$PROJECT/frontend/src/components/library/AlbumGrid.tsx"  "Album grid view with cover art — see Architecture §6.5"
placeholder "$PROJECT/frontend/src/components/library/ArtistList.tsx" "Artist discography list — see Architecture §6.5"
placeholder "$PROJECT/frontend/src/components/library/TrackTable.tsx" "Track table with sort — see Architecture §6.5"
placeholder "$PROJECT/frontend/src/components/search/SearchModal.tsx"     "Search modal: Navidrome instant results + YouTube WS streaming — see Architecture §3.1"
placeholder "$PROJECT/frontend/src/components/search/SearchResult.tsx"    "Single search result card — uses GlassCard variant=interactive"
placeholder "$PROJECT/frontend/src/components/search/SourceBadge.tsx"     "Library vs YouTube source badge — uses GlassCardBadge"
placeholder "$PROJECT/frontend/src/components/tagging/TaggingPanel.tsx"   "Bottom sheet (mobile) / right drawer (desktop) — see Architecture §6.4"
placeholder "$PROJECT/frontend/src/components/tagging/MetadataField.tsx"  "Single tag field with confidence badge + MusicBrainz fuzzy dropdown"
placeholder "$PROJECT/frontend/src/components/tagging/MBSuggest.tsx"      "MusicBrainz suggestion dropdown (300ms debounce) — see Architecture §3.3"

# Frontend tests
mkdir -p "$PROJECT/frontend/tests/unit" "$PROJECT/frontend/e2e"
placeholder "$PROJECT/frontend/tests/unit/subsonic.test.ts"  "Vitest unit tests for src/lib/subsonic.ts — see Testing spec §3.2.1"
placeholder "$PROJECT/frontend/tests/unit/player.test.ts"    "Vitest unit tests for src/store/player.ts — see Testing spec §3.2.2"
placeholder "$PROJECT/frontend/tests/unit/requestId.test.ts" "Vitest unit tests for src/middleware.ts — see Testing spec §3.2.3"
placeholder "$PROJECT/frontend/e2e/auth.spec.ts"             "Playwright E2E: auth flows — see Testing spec §6.2"
placeholder "$PROJECT/frontend/e2e/acquisition.spec.ts"      "Playwright E2E: search + acquisition + tagging — see Testing spec §6.3"
placeholder "$PROJECT/frontend/e2e/player.spec.ts"           "Playwright E2E: player flows + PWA cache — see Testing spec §6.4"
placeholder "$PROJECT/frontend/e2e/playwright.config.ts"     "Playwright config: Chromium + WebKit + Mobile Chrome — see Testing spec §6.5"
placeholder "$PROJECT/frontend/e2e/global-setup.ts"          "Playwright global setup: POST /api/auth/setup before all tests"
placeholder "$PROJECT/frontend/e2e/global-teardown.ts"       "Playwright global teardown: wipe test DB + tmp dirs"
cat > "$PROJECT/frontend/e2e/constants.ts" << 'EOF'
/**
 * E2E timing constants — single source of truth for all Playwright wait times.
 * Values match the Architecture spec exactly. Change here, nowhere else.
 */
export const TAGGING_PANEL_DELAY_MS    = 3_000;   // Architecture §6.4
export const STREAM_START_MAX_MS       = 5_000;   // Architecture §3.2
export const LIBRARY_READY_RACE_DELAY_MS = 20_000; // Testing spec §6.3
export const WS_RECONNECT_MAX_MS       = 30_000;  // Architecture §4.2
EOF

echo "✓ Frontend placeholder files created"

# =============================================================================
# 6. Config files
# =============================================================================

# pyproject.toml
cat > "$PROJECT/pyproject.toml" << 'EOF'
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]

[tool.coverage.run]
source = ["backend"]
omit = ["backend/tests/*", "backend/plugins/youtube.py"]

[tool.coverage.report]
fail_under = 85
show_missing = true

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
EOF

# backend Dockerfile
cat > "$PROJECT/backend/Dockerfile" << 'EOF'
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

# frontend Dockerfile
cat > "$PROJECT/frontend/Dockerfile" << 'EOF'
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
EOF

# docker-compose.yml
cat > "$PROJECT/docker-compose.yml" << 'EOF'
services:
  navidrome:
    image: deluan/navidrome:latest
    restart: unless-stopped
    volumes:
      - ./data/library:/music:ro
      - navidrome_data:/data
    ports:
      - "4533:4533"

  harmonia-backend:
    build: ./backend
    restart: unless-stopped
    volumes:
      - ./data:/data
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - navidrome

  harmonia-frontend:
    build: ./frontend
    restart: unless-stopped
    env_file: .env
    ports:
      - "3000:3000"
    depends_on:
      - harmonia-backend

volumes:
  navidrome_data:
EOF

# docker-compose.test.yml
cat > "$PROJECT/docker-compose.test.yml" << 'EOF'
services:
  harmonia-backend:
    build: ./backend
    environment:
      - HARMONIA_MOCK_PLUGINS=true
      - JWT_SECRET=test-secret-for-ci-only-not-used-in-production
      - NAVIDROME_URL=http://mock-navidrome:4533
      - NAVIDROME_ADMIN_USER=admin
      - NAVIDROME_ADMIN_PASS=admin
      - NAVIDROME_APP_USER=app
      - NAVIDROME_APP_PASS=app
      - MUSICBRAINZ_CONTACT_URL=https://github.com/test/harmonia
      - LOG_FORMAT=pretty
    ports:
      - "8000:8000"

  harmonia-frontend:
    build: ./frontend
    environment:
      - NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
      - NEXT_PUBLIC_NAVIDROME_URL=http://localhost:4533
    ports:
      - "3000:3000"
    depends_on:
      - harmonia-backend
EOF

# GitHub Actions CI
cat > "$PROJECT/.github/workflows/ci.yml" << 'EOF'
name: CI

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r backend/requirements-dev.txt
      - run: pytest backend/tests/ -v --cov=backend --cov-report=xml
      - uses: codecov/codecov-action@v4

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci
      - run: cd frontend && npx vitest run --coverage

  e2e-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci
      - run: npx playwright install --with-deps chromium webkit
      - run: docker compose -f docker-compose.test.yml up -d
      - run: cd frontend && npx playwright test
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report/
EOF

# .gitignore
cat > "$PROJECT/.gitignore" << 'EOF'
# Environment
.env
*.env.local

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.coverage
coverage.xml
htmlcov/
dist/
*.egg-info/
.venv/
venv/

# Node
node_modules/
.next/
out/
coverage/
playwright-report/
test-results/

# Data (never commit user data)
data/
*.db
*.sqlite

# Editor
.DS_Store
.idea/
.vscode/
*.swp
EOF

# next.config.ts
cat > "$PROJECT/frontend/next.config.ts" << 'EOF'
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
EOF

# tsconfig.json
cat > "$PROJECT/frontend/tsconfig.json" << 'EOF'
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
EOF

# postcss.config.js
cat > "$PROJECT/frontend/postcss.config.js" << 'EOF'
module.exports = {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
EOF

# vitest.config.ts
cat > "$PROJECT/frontend/vitest.config.ts" << 'EOF'
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
    },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
EOF

# vitest setup
cat > "$PROJECT/frontend/tests/setup.ts" << 'EOF'
import "@testing-library/jest-dom";
EOF

# globals.css
mkdir -p "$PROJECT/frontend/src/app"
cat > "$PROJECT/frontend/src/app/globals.css" << 'EOF'
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: #0F0E17;
    --foreground: #F0EEF8;
  }

  body {
    background-color: #0F0E17;
    color: #F0EEF8;
    font-family: "Inter Variable", "Inter", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  /* Scrollbar styling — matches the navy/purple palette */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(155, 135, 255, 0.3); border-radius: 9999px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(155, 135, 255, 0.5); }
}
EOF

# lib/utils.ts (cn helper — required by GlassCard and shadcn)
cat > "$PROJECT/frontend/src/lib/utils.ts" << 'EOF'
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely. Used everywhere in components. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
EOF

echo "✓ Config files created"

# =============================================================================
# 7. Data directory (gitignored)
# =============================================================================
mkdir -p "$PROJECT/data/"{raw,library}
touch "$PROJECT/data/.gitkeep"
echo "✓ Data directories created"

# =============================================================================
# 8. Git init + initial commit (skipped if git user not configured)
# =============================================================================
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  git init -q
fi
git add .
if git config user.email > /dev/null 2>&1; then
  git commit -q -m "chore: initial scaffold — all pre-written files + full placeholder tree"
  echo "✓ Git initial commit created"
else
  echo "✓ Files staged in git (run: git commit -m \"chore: initial scaffold\" to commit)"
fi

echo ""
echo "============================================================"
echo "  Harmonia scaffold complete!"
echo "============================================================"
echo ""
echo "  Project:   $(pwd)"
echo ""
echo "  Next steps:"
echo ""
echo "  1. cd $PROJECT"
echo "  2. cp .env.example .env"
echo "  3. Fill in JWT_SECRET, MUSICBRAINZ_CONTACT_URL in .env"
echo "  4. Generate audio_sample.opus fixture:"
echo "     ffmpeg -f lavfi -i sine=frequency=440:duration=3 \\"
echo "       -c:a libopus backend/tests/fixtures/ytdlp/audio_sample.opus"
echo "  5. cd backend && pip install -r requirements-dev.txt"
echo "  6. cd ../frontend && npm install"
echo "  7. Start coding — Phase 1 begins with backend/services/job_store.py"
echo ""
echo "  Pre-written files in place:"
echo "    backend/schemas.py       backend/database.py"
echo "    backend/auth.py          backend/config.py"
echo "    backend/main.py          backend/middleware.py"
echo "    backend/plugin_base.py   backend/routers/auth.py"
echo "    backend/tests/conftest.py"
echo "    frontend/src/lib/types.ts"
echo "    frontend/src/components/ui/GlassCard.tsx"
echo "    frontend/tailwind.config.ts"
echo ""
echo "  All other files are stubs awaiting implementation."
echo "  Each stub has a one-line comment pointing to the spec section."
echo "============================================================"
