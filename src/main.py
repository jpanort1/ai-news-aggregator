"""
main.py — Orchestrator for AI News & Tools Aggregator v2.0.
"""

import logging
import sys
import time
from datetime import datetime, timezone

# Configure logging before any imports that use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from collector import collect_all
from enricher import enrich_all as enrich_content
from dedup import load_hashes, filter_new, save_hashes, compute_new_hashes
from ai_enricher import enrich_all as enrich_ai
from sheets_writer import write_and_enforce


def main() -> None:
    start_time = time.time()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("=== AI News Aggregator v2.0 — run started at %s ===", run_ts)

    # 1. Collect raw items from all sources
    raw_items = collect_all()
    logger.info("Step 1 — Collected: %d raw items", len(raw_items))

    if not raw_items:
        logger.info("No items collected. Exiting.")
        return

    # 2. Enrich content (fetch full article text)
    enriched = enrich_content(raw_items)
    logger.info("Step 2 — Content enrichment done: %d items", len(enriched))

    # 3. Deduplicate
    hashes = load_hashes()
    new_items = filter_new(enriched, hashes)
    logger.info("Step 3 — After dedup: %d new items (discarded %d duplicates)",
                len(new_items), len(enriched) - len(new_items))

    if not new_items:
        logger.info("No new items after deduplication. Exiting.")
        return

    # 4. AI enrichment (summary, category, relevance, tags)
    processed = enrich_ai(new_items)
    logger.info("Step 4 — AI enrichment done: %d items", len(processed))

    # 5. Write to Google Sheets
    written = write_and_enforce(processed)
    logger.info("Step 5 — Written to Sheets: %d items", written)

    # 6. Save updated hashes
    new_hashes = compute_new_hashes(new_items)
    save_hashes(new_hashes)
    logger.info("Step 6 — Saved %d new hashes", len(new_hashes))

    elapsed = time.time() - start_time
    provider_counts = {}
    for item in processed:
        provider_counts[item.ai_provider] = provider_counts.get(item.ai_provider, 0) + 1

    provider_str = " | ".join(f"{p}={c}" for p, c in provider_counts.items())
    logger.info(
        "=== Done in %.1fs — Added %d items | Providers: %s ===",
        elapsed, written, provider_str
    )


if __name__ == "__main__":
    main()
