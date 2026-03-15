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
