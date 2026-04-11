"""
collector.py — Fetch raw items from all sources defined in config/sources.yaml.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import feedparser
import requests
import yaml
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")


@dataclass
class SourceConfig:
    name: str
    url: str
    type: str          # "rss" | "hn_api"
    language: str      # "EN" | "ES"
    default_type: str  # "noticia" | "herramienta"
    keywords: List[str] = field(default_factory=list)


@dataclass
class RawItem:
    title: str
    url: str
    published_at: datetime
    description: str
    source_name: str
    language: str
    default_type: str


def load_sources() -> List[SourceConfig]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sources = []
    for s in data.get("sources", []):
        sources.append(SourceConfig(
            name=s["name"],
            url=s["url"],
            type=s["type"],
            language=s["language"],
            default_type=s["default_type"],
            keywords=s.get("keywords", []),
        ))
    return sources


def _is_recent(dt: datetime, days: int = 7) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return dateparser.parse(val).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_rss(source: SourceConfig) -> List[RawItem]:
    try:
        feed = feedparser.parse(source.url, request_headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", source.name, e)
        return []

    if feed.bozo and not feed.entries:
        logger.warning("Bozo feed (malformed) for %s", source.name)
        return []

    items = []
    for entry in feed.entries:
        title = getattr(entry, "title", "").strip()
        url = getattr(entry, "link", "").strip()
        description = (
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
        ).strip()
        published_at = _parse_date(entry)

        # Quality filters
        if len(title.split()) < 5:
            continue
        if not url.startswith("https://"):
            continue
        if not _is_recent(published_at):
            continue

        items.append(RawItem(
            title=title,
            url=url,
            published_at=published_at or datetime.now(timezone.utc),
            description=description[:500],
            source_name=source.name,
            language=source.language,
            default_type=source.default_type,
        ))

    logger.info("RSS %s: %d items fetched", source.name, len(items))
    return items


def fetch_hackernews(config: SourceConfig) -> List[RawItem]:
    base = config.url.rstrip("/")
    keywords_lower = [k.lower() for k in config.keywords]
    items = []

    try:
        resp = requests.get(f"{base}/topstories.json", timeout=15)
        resp.raise_for_status()
        story_ids = resp.json()[:100]
    except Exception as e:
        logger.warning("HN topstories fetch failed: %s", e)
        return []

    for story_id in story_ids:
        if len(items) >= 30:
            break
        try:
            r = requests.get(f"{base}/item/{story_id}.json", timeout=10)
            r.raise_for_status()
            story = r.json()
        except Exception:
            continue

        if not story:
            continue

        title = story.get("title", "")
        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
        score = story.get("score", 0)
        time_unix = story.get("time", 0)

        if score <= 10:
            continue
        if not any(kw in title.lower() for kw in keywords_lower):
            continue
        if not url.startswith("https://"):
            url = f"https://news.ycombinator.com/item?id={story_id}"
        if len(title.split()) < 5:
            continue

        published_at = datetime.fromtimestamp(time_unix, tz=timezone.utc) if time_unix else datetime.now(timezone.utc)
        if not _is_recent(published_at):
            continue

        items.append(RawItem(
            title=title,
            url=url,
            published_at=published_at,
            description=f"HN score: {score}. {title}",
            source_name=config.name,
            language=config.language,
            default_type=config.default_type,
        ))
        time.sleep(0.1)  # light rate limiting

    logger.info("HN: %d items fetched", len(items))
    return items


def collect_all() -> List[RawItem]:
    sources = load_sources()
    all_items: List[RawItem] = []

    for source in sources:
        if source.type == "rss":
            all_items.extend(fetch_rss(source))
        elif source.type == "hn_api":
            all_items.extend(fetch_hackernews(source))
        else:
            logger.warning("Unknown source type: %s", source.type)

    logger.info("Total raw items collected: %d", len(all_items))
    return all_items
