"""Tests for the BEP Google Doc activity fetcher."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "build" / "fetch_bep_doc_activity.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fetch_bep_doc_activity", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_bep_doc_activity"] = module
    spec.loader.exec_module(module)
    return module


def test_extract_doc_id_from_typical_url() -> None:
    mod = _load_module()
    doc_id = "1kyw9mGgacNqeMbp4xZet3RnDhcMmf4_BmRgKaOkO2Sc"
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    assert mod.extract_doc_id(url) == doc_id


def test_extract_doc_id_returns_none_when_unparseable() -> None:
    mod = _load_module()
    assert mod.extract_doc_id("https://example.org/not-a-doc") is None


def test_fetch_modified_time_success(requests_mock) -> None:
    mod = _load_module()
    doc_id = "abc123"
    requests_mock.get(
        mod.DRIVE_API_URL.format(file_id=doc_id),
        json={"modifiedTime": "2026-01-15T10:00:00.000Z", "name": "BEP doc"},
    )
    assert (
        mod.fetch_modified_time(doc_id, api_key="fake-key")
        == "2026-01-15T10:00:00.000Z"
    )


def test_fetch_modified_time_returns_none_on_error(requests_mock) -> None:
    mod = _load_module()
    doc_id = "private-doc"
    requests_mock.get(
        mod.DRIVE_API_URL.format(file_id=doc_id),
        status_code=403,
        text="The caller does not have permission",
    )
    assert mod.fetch_modified_time(doc_id, api_key="fake-key") is None


def test_update_status_keeps_previous_entry_on_fetch_failure(
    requests_mock,
) -> None:
    """A transient fetch failure must not blank out a known-good status."""
    mod = _load_module()
    beps = [
        {
            "number": "099",
            "google_doc": "https://docs.google.com/document/d/deadbeef/",
        }
    ]
    requests_mock.get(
        mod.DRIVE_API_URL.format(file_id="deadbeef"),
        status_code=500,
        text="server error",
    )
    previous_status = {
        "099": {
            "last_modified": "2025-06-01T00:00:00.000Z",
            "checked_at": "2025-06-01T00:00:00+00:00",
        }
    }

    updated = mod.update_status(
        beps, api_key="fake-key", status=previous_status
    )

    assert updated["099"]["last_modified"] == "2025-06-01T00:00:00.000Z"


def test_update_status_records_new_entry_on_success(requests_mock) -> None:
    mod = _load_module()
    beps = [
        {
            "number": "100",
            "google_doc": "https://docs.google.com/document/d/cafef00d/",
        }
    ]
    requests_mock.get(
        mod.DRIVE_API_URL.format(file_id="cafef00d"),
        json={"modifiedTime": "2026-08-01T00:00:00.000Z"},
    )

    updated = mod.update_status(beps, api_key="fake-key", status={})

    assert updated["100"]["last_modified"] == "2026-08-01T00:00:00.000Z"
    assert "checked_at" in updated["100"]


def test_update_status_skips_beps_without_a_google_doc() -> None:
    mod = _load_module()
    beps = [{"number": "101", "google_doc": None}]

    updated = mod.update_status(beps, api_key="fake-key", status={})

    assert updated == {}
