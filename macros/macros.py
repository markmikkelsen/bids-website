from datetime import UTC, datetime
from pathlib import Path

import ruamel.yaml
from bidsschematools import render, schema
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich import print

yaml = ruamel.yaml.YAML()
yaml.indent(mapping=2, sequence=4, offset=2)

ROOT = Path(__file__).parents[1]

TEMPLATES_DIR = ROOT / "templates"

WEBSITE_DATA_DIR = ROOT / "data"

# Thresholds (in days since a BEP's Google Doc was last edited) used to
# turn "modifiedTime" into a traffic-light activity badge on the BEPs
# dashboard. See ``fetch_bep_status`` and ``generate_beps_status_summary``.
FRESH_AFTER_DAYS = 30
ACTIVE_AFTER_DAYS = 180


def return_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(),
        lstrip_blocks=True,
        trim_blocks=True,
    )


def generate_converter_table(file: str, data_type: str) -> str:
    input_file = WEBSITE_DATA_DIR / "tools" / file
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("converters_table_md.jinja")
    return template.render(include=content, data_type=data_type)


def generate_tools_table(file: str, category=None) -> str:
    input_file = WEBSITE_DATA_DIR / "tools" / file
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("tools_table_md.jinja")
    return template.render(include=content, category=category)


def generate_members_table(file: str) -> str:
    input_file = WEBSITE_DATA_DIR / "people" / file
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("members_table_html.jinja")
    return template.render(include=content[0])


def load_bep_status(file: str = "beps_status.yml") -> dict:
    """Load the cached Google Doc activity status for BEPs.

    Returns an empty mapping if the cache doesn't exist yet or is empty,
    so the dashboard degrades gracefully (everything shows as
    "unknown") instead of failing the build.
    """
    input_file = WEBSITE_DATA_DIR / "beps" / file
    if not input_file.exists():
        return {}
    return yaml.load(input_file) or {}


def bep_activity_badge(
    last_modified: str | None, edits_since_last_check: int | None = None
) -> dict[str, str]:
    """Turn a Google Doc's ``modifiedTime`` into a display badge.

    ``edits_since_last_check`` (a diff of the Drive API's ``version``
    field between two runs of the fetcher) is appended to the label
    when available, giving a rough sense of *how much* changed, not
    just *whether* it did.

    Returns a dict with ``icon``, ``label`` and ``category`` so
    templates only need to display values, not compute them.
    """
    if not last_modified:
        return {
            "icon": "\N{MEDIUM WHITE CIRCLE}",
            "label": "Unknown",
            "category": "unknown",
        }

    modified = datetime.fromisoformat(last_modified)
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - modified).days

    if days <= FRESH_AFTER_DAYS:
        icon, category = "\N{LARGE GREEN CIRCLE}", "fresh"
    elif days <= ACTIVE_AFTER_DAYS:
        icon, category = "\N{LARGE YELLOW CIRCLE}", "active"
    else:
        icon, category = "\N{LARGE RED CIRCLE}", "stale"

    label = f"Edited {days} day{'s' if days != 1 else ''} ago"
    if edits_since_last_check is not None:
        label += (
            f" (+{edits_since_last_check} edit"
            f"{'s' if edits_since_last_check != 1 else ''} "
            "since last check)"
        )

    return {"icon": icon, "label": label, "category": category}


def generate_beps_table(
    file: str, bep_type: str | None = None, status_file: str | None = None
) -> str:
    input_file = WEBSITE_DATA_DIR / "beps" / file
    content = yaml.load(input_file)
    if bep_type == "draft":
        content = [x for x in content if x["pull_request_created"] is None]
    elif bep_type == "proposed":
        content = [x for x in content if x["pull_request_created"] is not None]

    status = {}
    if status_file is not None:
        raw_status = load_bep_status(status_file)
        status = {
            number: bep_activity_badge(
                entry.get("last_modified"),
                entry.get("edits_since_last_check"),
            )
            for number, entry in raw_status.items()
        }

    env = return_jinja_env()
    template = env.get_template("beps_table_md.jinja")
    return template.render(include=content, bep_type=bep_type, status=status)


def generate_beps_status_summary(
    beps_file: str = "beps.yml", status_file: str = "beps_status.yml"
) -> str:
    """Render a one-line summary of how fresh the draft BEPs' docs are."""
    beps = yaml.load(WEBSITE_DATA_DIR / "beps" / beps_file) or []
    draft_numbers = [
        bep["number"]
        for bep in beps
        if bep.get("pull_request_created") is None
    ]

    raw_status = load_bep_status(status_file)

    counts = {"fresh": 0, "active": 0, "stale": 0, "unknown": 0}
    checked_at = None
    for number in draft_numbers:
        entry = raw_status.get(number, {})
        checked_at = checked_at or entry.get("checked_at")
        badge = bep_activity_badge(
            entry.get("last_modified"), entry.get("edits_since_last_check")
        )
        counts[badge["category"]] += 1

    env = return_jinja_env()
    template = env.get_template("beps_status_summary_md.jinja")
    return template.render(counts=counts, checked_at=checked_at)


def generate_working_groups_table(file: str, status: str | None = None) -> str:
    input_file = WEBSITE_DATA_DIR / file
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("working_group_table_md.jinja")
    return template.render(include=content, status=status)


def generate_grants_table():
    input_file = WEBSITE_DATA_DIR / "grants.yml"
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("grants_table_md.jinja")
    return template.render(include=content)


def generate_apps_table():
    input_file = WEBSITE_DATA_DIR / "tools" / "apps.yml"
    content = yaml.load(input_file)
    env = return_jinja_env()
    template = env.get_template("apps_table_md.jinja")
    return template.render(include=content, type=type)


def generate_filename_templates():
    """Create filename templates for all datatypes of all modalities."""
    schema_obj = schema.load_schema()

    modalities = schema_obj.rules.modalities

    to_render = [
        {
            "name": x,
            "description": schema_obj.objects.modalities[x]["description"],
            "datatypes": [
                {
                    "name": dt,
                    "filenames": filename_template_for(schema_obj, dt),
                }
                for dt in modalities[x]["datatypes"]
            ],
        }
        for x in modalities
    ]

    env = return_jinja_env()
    template = env.get_template("filename_templates_md.jinja")
    return template.render(include=to_render)


def filename_template_for(schema_obj, datatype):
    """Create filename templates for a single datatype."""
    filenames = render.make_filename_template(
        dstype="raw",
        schema=schema_obj,
        src_path=Path("https://bids-specification.readthedocs.io/en/latest/"),
        pdf_format=False,
        datatypes=[datatype],
    )
    filenames = filenames.replace(
        "../../..",
        "https://bids-specification.readthedocs.io/en/latest",
    )
    return filenames


def main():
    print(generate_converter_table(file="converters.yml", data_type="MRI"))


if __name__ == "__main__":
    main()
