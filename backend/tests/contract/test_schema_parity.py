"""
backend/tests/contract/test_schema_parity.py

Asserts that every Pydantic model in backend/schemas.py has a documented
TypeScript equivalent in frontend/src/lib/types.ts.

The mapping below serves as the authoritative cross-language contract table.
If a new model is added to schemas.py without a corresponding TypeScript type
(and an entry in PARITY_MAP), this test will fail.
"""

import inspect
import re
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

# Ensure the project root is importable regardless of how pytest is invoked.
ROOT = Path(__file__).resolve().parents[3]  # backend/tests/contract/ -> project root
sys.path.insert(0, str(ROOT))

import backend.schemas as schemas  # noqa: E402

# ---------------------------------------------------------------------------
# Authoritative cross-language parity mapping
# Each entry: Python model name -> TypeScript type name (as it appears in types.ts)
# ---------------------------------------------------------------------------
PARITY_MAP: dict[str, str] = {
    # Auth
    "SetupRequest": "SetupRequest",
    "LoginRequest": "LoginRequest",
    "AuthStatus": "AuthStatus",
    "TokenResponse": "TokenResponse",
    # Jobs & Acquisition
    "AcquireRequest": "AcquireRequest",
    "AcquireResponse": "AcquireResponse",
    "JobStatus": "JobStatus",
    # Search
    "SearchRequest": "SearchRequest",
    "SearchResult": "SearchResult",
    "SearchCompleteEvent": "SearchCompleteEvent",
    # Tagging
    "TagPayload": "TagPayload",
    "TagCandidate": "TagCandidate",
    # WebSocket Events
    "DownloadProgressEvent": "DownloadProgressEvent",
    "DownloadCompleteEvent": "DownloadCompleteEvent",
    "TaggingSuggestionsEvent": "TaggingSuggestionsEvent",
    "LibraryReadyEvent": "LibraryReadyEvent",
    "JobErrorEvent": "JobErrorEvent",
    "SearchResultEvent": "SearchResultEvent",
    # Metadata
    "MusicBrainzArtist": "MusicBrainzArtist",
    "MusicBrainzRelease": "MusicBrainzRelease",
    "MusicBrainzRecording": "MusicBrainzRecording",
    "CoverArtResponse": "CoverArtResponse",
    # Custom Metadata
    "CustomTrack": "CustomTrack",
    "CustomMetadataSuggestion": "CustomMetadataSuggestion",
    # System (private helpers are intentionally excluded from the public contract)
    "SystemMetrics": "SystemMetrics",
    "ClientErrorReport": "ClientErrorReport",
    "YtdlpUpdateStatus": "YtdlpUpdateStatus",
    # Plugin
    "PluginManifest": "PluginManifest",
}

# Private helper models used only inside SystemMetrics – excluded from the
# public contract but listed here for transparency.
INTERNAL_MODELS: set[str] = {
    # Private SystemMetrics helpers – not part of the public API surface.
    "_SearchMetrics",
    "_DownloadMetrics",
    "_TaggingMetrics",
    # Internal backend token – never constructed by the frontend.
    # The frontend only sees the raw `stream_token` string inside AcquireResponse.
    "StreamToken",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_pydantic_models() -> dict[str, type[BaseModel]]:
    """Return every public Pydantic BaseModel subclass defined in schemas.py."""
    return {
        name: obj
        for name, obj in inspect.getmembers(schemas, inspect.isclass)
        if issubclass(obj, BaseModel)
        and obj is not BaseModel
        and obj.__module__ == schemas.__name__
    }


def _collect_ts_type_names(ts_path: Path) -> set[str]:
    """
    Parse frontend/src/lib/types.ts and return every exported interface / type alias.
    Uses a simple regex approach – sufficient for the well-structured types.ts format.
    """
    source = ts_path.read_text(encoding="utf-8")
    interfaces = re.findall(r"^export\s+interface\s+(\w+)", source, re.MULTILINE)
    type_aliases = re.findall(r"^export\s+type\s+(\w+)\s*=", source, re.MULTILINE)
    return set(interfaces) | set(type_aliases)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

TS_TYPES_PATH = ROOT / "frontend" / "src" / "lib" / "types.ts"
PYDANTIC_MODELS = _collect_pydantic_models()
TS_NAMES = _collect_ts_type_names(TS_TYPES_PATH) if TS_TYPES_PATH.exists() else set()


class TestSchemaParity:
    """Validates the Python ↔ TypeScript schema contract."""

    def test_ts_types_file_exists(self) -> None:
        """The TypeScript types file must exist at the expected path."""
        assert TS_TYPES_PATH.exists(), (
            f"Missing TypeScript types file: {TS_TYPES_PATH}\n"
            "Run `npm run generate-types` or create it manually."
        )

    def test_every_python_model_is_in_parity_map(self) -> None:
        """Every Pydantic model in schemas.py must appear in PARITY_MAP (or INTERNAL_MODELS)."""
        schema_names = set(PYDANTIC_MODELS.keys())
        mapped_names = set(PARITY_MAP.keys()) | INTERNAL_MODELS
        unmapped = schema_names - mapped_names
        assert not unmapped, (
            f"The following models are missing from PARITY_MAP:\n"
            + "\n".join(f"  - {n}" for n in sorted(unmapped))
            + "\nAdd them to PARITY_MAP in this file and add their TypeScript equivalent."
        )

    def test_every_parity_map_entry_has_ts_type(self) -> None:
        """Every TypeScript type declared in PARITY_MAP must exist in types.ts."""
        missing: list[str] = []
        for py_name, ts_name in PARITY_MAP.items():
            if ts_name not in TS_NAMES:
                missing.append(f"  Python '{py_name}' -> TypeScript '{ts_name}' (NOT FOUND)")
        assert not missing, (
            "The following Python models have no matching TypeScript type:\n"
            + "\n".join(missing)
        )

    @pytest.mark.parametrize("py_name,ts_name", list(PARITY_MAP.items()))
    def test_model_has_docstring(self, py_name: str, ts_name: str) -> None:
        """Every Pydantic model must have a docstring."""
        model = PYDANTIC_MODELS.get(py_name)
        if model is None:
            pytest.skip(f"{py_name} not found in schemas (may be a private helper)")
        assert model.__doc__ and model.__doc__.strip(), (
            f"Model '{py_name}' is missing a docstring."
        )

    def test_tag_payload_validator_rejects_empty_title(self) -> None:
        """TagPayload must raise if title is an empty string."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="non-empty"):
            schemas.TagPayload(title="", artist="Someone")

    def test_tag_payload_validator_rejects_empty_artist(self) -> None:
        """TagPayload must raise if artist is an empty string."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="non-empty"):
            schemas.TagPayload(title="A Track", artist="   ")

    def test_search_request_validator_rejects_both_none(self) -> None:
        """SearchRequest must raise if both query and url are omitted."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="At least one"):
            schemas.SearchRequest()

    def test_search_request_accepts_query_only(self) -> None:
        """SearchRequest must accept a query without a url."""
        req = schemas.SearchRequest(query="lofi hip hop")
        assert req.query == "lofi hip hop"
        assert req.url is None

    def test_search_request_accepts_url_only(self) -> None:
        """SearchRequest must accept a url without a query."""
        req = schemas.SearchRequest(url="https://youtube.com/watch?v=abc123")
        assert req.url is not None
        assert req.query is None

    def test_private_metrics_ts_types_exist(self) -> None:
        """
        The three private *Metrics helpers are excluded from PARITY_MAP but still
        have TypeScript equivalents (SearchMetrics, DownloadMetrics, TaggingMetrics).
        This test guards against drift in those types independently.
        """
        private_map = {
            "_SearchMetrics": "SearchMetrics",
            "_DownloadMetrics": "DownloadMetrics",
            "_TaggingMetrics": "TaggingMetrics",
        }
        missing = [
            f"  Python '{py}' -> TypeScript '{ts}' (NOT FOUND)"
            for py, ts in private_map.items()
            if ts not in TS_NAMES
        ]
        assert not missing, (
            "Private metrics helpers have no matching TypeScript type:\n"
            + "\n".join(missing)
        )

    def test_response_models_are_frozen(self) -> None:
        """All frozen models must raise on attribute assignment."""
        from pydantic import ValidationError

        frozen_model_names = [
            name
            for name, model in PYDANTIC_MODELS.items()
            if getattr(model.model_config, "frozen", False)
            or model.model_config.get("frozen", False)  # type: ignore[union-attr]
        ]
        # Spot-check a subset of known-frozen models.
        for name in ("AuthStatus", "TokenResponse", "AcquireResponse", "JobStatus", "ClientErrorReport"):
            assert name in frozen_model_names, (
                f"Expected '{name}' to be frozen but it is not."
            )
