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
