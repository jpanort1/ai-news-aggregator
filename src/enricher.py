"""
enricher.py — Fetch full article text to improve AI summary quality.
"""

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from dataclasses import dataclass

import requests
import trafilatura

from collector import RawItem

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AINewsBot/2.0)"}
MAX_CHARS = 3000
FETCH_TIMEOUT = 10
MAX_WORKERS = 5


@dataclass
class EnrichedItem:
    title: str
    url: str
    published_at: object
    description: str
    source_name: str
    language: str
    default_type: str
    full_text: str  # fetched article text (or fallback to description)


# Simple per-domain rate limiter: track last request time
_domain_last_request: dict = defaultdict(float)
_DOMAIN_MIN_INTERVAL = 1.0  # seconds between requests to same domain


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def fetch_article_text(url: str, fallback: str = "") -> str:
    domain = _domain_of(url)
    elapsed = time.time() - _domain_last_request[domain]
    if elapsed < _DOMAIN_MIN_INTERVAL:
        time.sleep(_DOMAIN_MIN_INTERVAL - elapsed)
    _domain_last_request[domain] = time.time()

    try:
        resp = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        if text:
            return text[:MAX_CHARS]
        logger.debug("trafilatura returned empty for %s, using fallback", url)
    except Exception as e:
        logger.debug("fetch_article_text failed for %s: %s", url, e)

    return fallback[:MAX_CHARS] if fallback else ""


def _enrich_one(item: RawItem) -> EnrichedItem:
    full_text = fetch_article_text(item.url, fallback=item.description)
    return EnrichedItem(
        title=item.title,
        url=item.url,
        published_at=item.published_at,
        description=item.description,
        source_name=item.source_name,
        language=item.language,
        default_type=item.default_type,
        full_text=full_text or item.description,
    )


def enrich_all(items: List[RawItem]) -> List[EnrichedItem]:
    results: List[EnrichedItem] = []
    failed_urls = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {executor.submit(_enrich_one, item): item for item in items}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("Enrichment failed for %s: %s", item.url, e)
                failed_urls.append(item.url)
                # Fallback: use description as full_text
                results.append(EnrichedItem(
                    title=item.title,
                    url=item.url,
                    published_at=item.published_at,
                    description=item.description,
                    source_name=item.source_name,
                    language=item.language,
                    default_type=item.default_type,
                    full_text=item.description,
                ))

    if failed_urls:
        logger.info("Content fetch failed for %d URLs: %s", len(failed_urls), failed_urls[:5])

    logger.info("Content enrichment done: %d/%d items enriched", len(results) - len(failed_urls), len(results))
    return results
