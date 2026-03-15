/**
 * E2E timing constants — single source of truth for all Playwright wait times.
 * Values match the Architecture spec exactly. Change here, nowhere else.
 */
export const TAGGING_PANEL_DELAY_MS    = 3_000;   // Architecture §6.4
export const STREAM_START_MAX_MS       = 5_000;   // Architecture §3.2
export const LIBRARY_READY_RACE_DELAY_MS = 20_000; // Testing spec §6.3
export const WS_RECONNECT_MAX_MS       = 30_000;  // Architecture §4.2
