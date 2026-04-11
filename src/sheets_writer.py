"""
sheets_writer.py — Write processed items to Google Sheets and enforce retention policy.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import List

import gspread
from google.oauth2.service_account import Credentials

from ai_enricher import ProcessedItem

logger = logging.getLogger(__name__)

SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

FEED_SHEET = "AI_Feed"
META_SHEET = "_meta"
MAX_ITEMS = 1000

HEADERS = ["fecha", "tipo", "categoria", "relevancia", "nombre", "link",
           "precio", "resumen", "tags", "fuente", "idioma"]

PRICE_PATTERNS = [
    r"\$[\d,.]+\s*(?:/mo|/month|/mes|/year|/yr)?",
    r"€[\d,.]+\s*(?:/mo|/month|/mes|/year|/yr)?",
    r"\b(?:free|gratis|gratuito|freemium|open[\s-]source)\b",
]


def _classify_precio(item: ProcessedItem) -> str:
    if item.default_type != "herramienta":
        return "Noticia"
    text = (item.resumen + " " + item.description).lower()
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group().strip()
    return "Ver enlace"


def _format_date(dt) -> str:
    if dt is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


def connect() -> gspread.Client:
    if not GOOGLE_CREDENTIALS_JSON:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_sheet(spreadsheet, name: str):
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        return ws


def write_items(spreadsheet, items: List[ProcessedItem]) -> int:
    if not items:
        return 0

    ws = _get_or_create_sheet(spreadsheet, FEED_SHEET)

    # Ensure headers exist
    existing = ws.row_values(1)
    if not existing or existing[0] != "fecha":
        ws.insert_row(HEADERS, 1)

    rows = []
    for item in items:
        tags_str = ", ".join(item.tags)
        precio = _classify_precio(item)
        row = [
            _format_date(item.published_at),
            item.default_type,
            item.categoria,
            item.relevancia,
            item.title,
            item.url,
            precio,
            item.resumen,
            tags_str,
            item.source_name,
            item.language,
        ]
        rows.append(row)

    ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("Wrote %d rows to %s", len(rows), FEED_SHEET)

    _update_meta(spreadsheet, len(rows))
    return len(rows)


def _update_meta(spreadsheet, items_added: int) -> None:
    try:
        ws = _get_or_create_sheet(spreadsheet, META_SHEET)
        feed_ws = spreadsheet.worksheet(FEED_SHEET)
        total = max(0, feed_ws.row_count - 1)  # subtract header

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Meta sheet: row 1 = headers, row 2 = values
        meta_headers = ["last_run", "items_total", "items_last_run"]
        meta_values = [now, total, items_added]

        existing_headers = ws.row_values(1)
        if not existing_headers or existing_headers[0] != "last_run":
            ws.update("A1", [meta_headers])

        ws.update("A2", [meta_values])
    except Exception as e:
        logger.warning("Failed to update _meta: %s", e)


def enforce_retention(spreadsheet, max_items: int = MAX_ITEMS) -> None:
    ws = spreadsheet.worksheet(FEED_SHEET)
    all_rows = ws.get_all_values()

    if not all_rows:
        return

    header = all_rows[0]
    data_rows = all_rows[1:]
    total = len(data_rows)

    if total <= max_items:
        logger.info("Retention: %d items, within limit of %d", total, max_items)
        return

    excess = total - max_items
    rows_to_archive = data_rows[:excess]
    rows_to_keep = data_rows[excess:]

    logger.info("Retention: archiving %d items (total was %d)", excess, total)

    # Write to archive sheet
    year = datetime.now(timezone.utc).year
    archive_name = f"AI_Feed_Archive_{year}"
    archive_ws = _get_or_create_sheet(spreadsheet, archive_name)

    # Check if archive already has data (beyond header)
    archive_existing = archive_ws.get_all_values()
    if len(archive_existing) <= 1:
        archive_ws.append_rows(rows_to_archive)
    else:
        archive_ws.append_rows(rows_to_archive)

    # Rewrite AI_Feed with only kept rows
    ws.clear()
    ws.update("A1", [header] + rows_to_keep)
    logger.info("Retention enforced: AI_Feed now has %d items", len(rows_to_keep))


def write_and_enforce(items: List[ProcessedItem]) -> int:
    """Full write pipeline with retry logic."""
    if not SHEET_ID:
        raise ValueError("SHEET_ID environment variable not set")

    for attempt in range(3):
        try:
            client = connect()
            spreadsheet = client.open_by_key(SHEET_ID)
            written = write_items(spreadsheet, items)
            enforce_retention(spreadsheet)
            return written
        except Exception as e:
            logger.warning("Sheets write attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt)

    raise RuntimeError("Google Sheets write failed after 3 attempts")
