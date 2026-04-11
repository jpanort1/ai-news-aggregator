"""
dedup.py — URL-based deduplication using a SHA256 hash file in the repo.
"""

import hashlib
import json
import logging
import os
from typing import List, Set

from enricher import EnrichedItem

logger = logging.getLogger(__name__)

HASHES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "hashes.json")
MAX_HASHES = 50_000


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()


def load_hashes() -> Set[str]:
    if not os.path.exists(HASHES_PATH):
        logger.info("hashes.json not found — starting fresh")
        return set()
    try:
        with open(HASHES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        return set(data)
    except Exception as e:
        logger.warning("hashes.json corrupt (%s) — initializing empty set", e)
        return set()


def filter_new(items: List[EnrichedItem], hashes: Set[str]) -> List[EnrichedItem]:
    new_items = []
    for item in items:
        h = _hash_url(item.url)
        if h not in hashes:
            new_items.append(item)
    logger.info("Dedup: %d new out of %d total", len(new_items), len(items))
    return new_items


def save_hashes(new_hashes: Set[str]) -> None:
    existing = load_hashes()
    combined = existing | new_hashes

    # Keep only the most recent MAX_HASHES (by treating them as an ordered list)
    if len(combined) > MAX_HASHES:
        # Convert to list; trim oldest by slicing (approximation — no timestamp on hashes)
        combined_list = list(combined)[-MAX_HASHES:]
    else:
        combined_list = list(combined)

    with open(HASHES_PATH, "w", encoding="utf-8") as f:
        json.dump(combined_list, f)

    logger.info("Saved %d hashes to hashes.json", len(combined_list))


def compute_new_hashes(items: List[EnrichedItem]) -> Set[str]:
    return {_hash_url(item.url) for item in items}
