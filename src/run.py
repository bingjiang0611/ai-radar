"""ai-radar render entrypoint.

Daily operation is intentionally boring: read curated rows from SQLite and render
the static site. There is no RSS/X/browser fetch path in this command.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content  # noqa: E402
from render import render_site  # noqa: E402
from store import all_items, purge_old  # noqa: E402

RETENTION_DAYS = 7


def is_curated_item(item):
    return bool(
        item.get("source_id") == "user-curated"
        or (item.get("translation_md") or "").strip()
        or (item.get("summary_md") or "").strip()
        or "bilibili" in (item.get("video_url") or "")
    )


def render_current():
    purged = purge_old(RETENTION_DAYS)
    db_items = all_items()
    items = [i for i in db_items if is_curated_item(i)]
    removed_imgs = content.gc_images(
        [i.get("content_html", "") for i in db_items]
        + [i.get("translation_md", "") for i in db_items]
        + [i.get("summary_md", "") for i in db_items]
        + [i.get("tweet_meta", "") for i in db_items]
    )
    if purged or removed_imgs:
        print(f"retention: purged {purged} rows, removed {removed_imgs} images")
    out = render_site(items, interactions={"user-curated": "detail"})
    print(f"rendered {len(items)}/{len(db_items)} curated items -> {out}")
    return out, len(items)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Render curated ai-radar content.")
    return p.parse_args(argv)


def main(argv=None):
    parse_args(argv)
    render_current()


if __name__ == "__main__":
    main()
