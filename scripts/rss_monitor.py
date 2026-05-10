import feedparser
import json
import os
from pathlib import Path

AMEBLO_RSS_URL = os.getenv("AMEBLO_RSS_URL", "https://ameblo.jp/pulinet/rss20.xml")
DATA_FILE = Path(__file__).parent.parent / "data" / "published.json"


def _ensure_data_file():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        with open(DATA_FILE, "w") as f:
            json.dump([], f)


def load_published() -> set:
    _ensure_data_file()
    with open(DATA_FILE) as f:
        return set(json.load(f))


def save_published(published: set):
    _ensure_data_file()
    with open(DATA_FILE, "w") as f:
        json.dump(sorted(list(published)), f, ensure_ascii=False, indent=2)


def fetch_new_entries() -> list[dict]:
    feed = feedparser.parse(AMEBLO_RSS_URL)
    published = load_published()

    new_entries = []
    for entry in feed.entries:
        entry_id = entry.get("id") or entry.get("link", "")
        if entry_id and entry_id not in published:
            content_html = ""
            if entry.get("content"):
                content_html = entry.content[0].get("value", "")
            elif entry.get("summary"):
                content_html = entry.summary

            new_entries.append(
                {
                    "id": entry_id,
                    "title": entry.get("title", ""),
                    "content": content_html,
                    "link": entry.get("link", ""),
                }
            )

    return new_entries


def mark_as_published(entry_id: str):
    published = load_published()
    published.add(entry_id)
    save_published(published)
