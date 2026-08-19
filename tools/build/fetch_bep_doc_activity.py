"""Fetch activity signals for draft/proposed BEP Google Docs.

Populates ``data/beps/beps_status.yml`` from the Google Drive API so the
BEP dashboard (see ``docs/extensions/beps.md``) can show how recently -
and how much - each BEP's Google Doc has actually been touched.

This only reads file *metadata* via the Drive API, using a plain API
key - it therefore only works for BEP Google Docs shared as "Anyone
with the link can view" (or more open), which is the norm for BEP
drafts. Docs that are not link-shared simply keep whatever status was
last recorded (or stay unrecorded, which the dashboard shows as
"unknown"). Two fields come out of this:

- ``modifiedTime``: when the doc was last edited.
- ``version``: an integer Google increments on every save. Comparing
  it to the value recorded on the *previous* run gives a rough "how
  many edits since we last checked" count - useful extra signal, and
  still just an API key call (unlike comment counts or full revision
  history, which need OAuth/a service account).

Requires the ``GOOGLE_API_KEY`` environment variable, pointing at an API
key with the Google Drive API enabled. Meant to run on a schedule (see
``.github/workflows/bep-doc-status.yml``), not as part of the regular
site build: regular builds - including PRs from forks, which don't have
access to secrets - just read the checked-in ``beps_status.yml`` cache.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

import requests
from bids_website.utils import data_dir
from rich import print
from ruamel.yaml import YAML

DRIVE_FILE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")
DRIVE_API_URL = "https://www.googleapis.com/drive/v3/files/{file_id}"
DRIVE_FIELDS = "modifiedTime,version,name"
REQUEST_TIMEOUT = 15

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.default_flow_style = False

safe_yaml = YAML(typ="safe", pure=True)


def status_file():
    return data_dir() / "beps" / "beps_status.yml"


def extract_doc_id(google_doc_url: str) -> str | None:
    """Pull the Drive file id out of a Google Doc URL."""
    match = DRIVE_FILE_ID_RE.search(google_doc_url)
    return match.group(1) if match else None


def fetch_doc_metadata(doc_id: str, api_key: str) -> dict | None:
    """Return ``{"modified_time": ..., "version": ...}``, or ``None``.

    ``version`` comes back from the Drive API as a stringified int64;
    it is returned as-is here (still a string) and parsed by callers.
    """
    response = requests.get(
        DRIVE_API_URL.format(file_id=doc_id),
        params={"fields": DRIVE_FIELDS, "key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        print(
            f"[yellow]Could not fetch metadata for doc {doc_id} "
            f"(HTTP {response.status_code}): {response.text[:200]}[/yellow]"
        )
        return None

    data = response.json()
    return {
        "modified_time": data.get("modifiedTime"),
        "version": data.get("version"),
    }


def compute_edits_since_last_check(
    previous_version: str | None, current_version: str | None
) -> int | None:
    """Diff two Drive ``version`` values into an edit count.

    Returns ``None`` when there's nothing to compare against (first
    time this BEP is checked) or the values can't be parsed. A
    negative diff would mean the doc's version went backwards, which
    shouldn't happen - treated as "nothing to report" rather than
    trusted.
    """
    if previous_version is None or current_version is None:
        return None
    try:
        diff = int(current_version) - int(previous_version)
    except (TypeError, ValueError):
        return None
    return diff if diff >= 0 else None


def load_beps() -> list[dict]:
    with (data_dir() / "beps" / "beps.yml").open() as f:
        return safe_yaml.load(f) or []


def load_existing_status() -> dict:
    if not status_file().exists():
        return {}
    with status_file().open() as f:
        return yaml.load(f) or {}


def update_status(beps: list[dict], api_key: str, status: dict) -> dict:
    """Refresh ``status`` in place for every BEP with a Google Doc."""
    checked_at = datetime.now(UTC).isoformat(timespec="seconds")

    for bep in beps:
        google_doc = bep.get("google_doc")
        number = bep["number"]
        if not google_doc:
            continue

        doc_id = extract_doc_id(google_doc)
        if doc_id is None:
            print(
                f"[yellow]BEP {number}: could not parse a doc id "
                f"out of {google_doc!r}[/yellow]"
            )
            continue

        metadata = fetch_doc_metadata(doc_id, api_key)
        if metadata is None or metadata["modified_time"] is None:
            # Keep whatever was last recorded rather than blanking it out -
            # a transient 403/404 shouldn't make a BEP look "unknown".
            continue

        previous_version = status.get(number, {}).get("version")
        edits_since_last_check = compute_edits_since_last_check(
            previous_version, metadata["version"]
        )

        status[number] = {
            "last_modified": metadata["modified_time"],
            "version": metadata["version"],
            "edits_since_last_check": edits_since_last_check,
            "checked_at": checked_at,
        }
        print(
            f"BEP {number}: last modified {metadata['modified_time']} "
            f"(version {metadata['version']}, "
            f"+{edits_since_last_check} since last check)"
        )

    return status


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GOOGLE_API_KEY is not set - refusing to run. This script is "
            "meant to run in the scheduled 'BEP doc status' GitHub Action, "
            "not locally or as part of a regular site build."
        )

    beps = load_beps()
    status = load_existing_status()
    status = update_status(beps, api_key, status)
    status = dict(sorted(status.items()))

    with status_file().open("w") as f:
        f.write(
            "# Auto-generated by tools/build/fetch_bep_doc_activity.py\n"
            '# via the scheduled "BEP doc status" GitHub Action (see\n'
            "# .github/workflows/bep-doc-status.yml).\n"
            "#\n"
            "# Do not edit by hand - changes will be overwritten on the "
            "next\n"
            "# scheduled run. Keyed by BEP number, matching "
            "data/beps/beps.yml.\n"
        )
        yaml.dump(status, f)


if __name__ == "__main__":
    main()
