"""
ai_enricher.py — AI enrichment: summary, category, relevance score, tags.
Primary: Groq (llama-3.1-8b-instant). Fallback: Gemini 1.5 Flash.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from enricher import EnrichedItem

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

VALID_CATEGORIES = {"Modelos", "Herramientas", "Investigacion", "Industria", "Normativa", "Tutoriales"}

SYSTEM_PROMPT = (
    "Eres un analista experto en inteligencia artificial. "
    "Dado el siguiente articulo, devuelve un JSON con estos campos:\n"
    "- resumen: string, 2-4 frases en el mismo idioma del articulo. "
    "Incluye el dato mas relevante (cifra, nombre de modelo, empresa, impacto).\n"
    "- categoria: uno de [Modelos, Herramientas, Investigacion, Industria, Normativa, Tutoriales]\n"
    "- relevancia: integer del 1 al 10 segun el impacto real en el sector IA global.\n"
    "- tags: array de 3-5 strings, keywords especificas del articulo.\n"
    "Devuelve SOLO el JSON, sin markdown, sin explicaciones."
)


@dataclass
class AIResult:
    resumen: str
    categoria: str
    relevancia: int
    tags: List[str]
    provider: str  # "groq" | "gemini" | "fallback"


@dataclass
class ProcessedItem:
    title: str
    url: str
    published_at: object
    description: str
    source_name: str
    language: str
    default_type: str
    full_text: str
    resumen: str
    categoria: str
    relevancia: int
    tags: List[str]
    ai_provider: str


def _build_prompt(item: EnrichedItem) -> str:
    content = item.full_text or item.description
    return f"Titulo: {item.title}\n\nContenido:\n{content[:2000]}"


def _parse_ai_response(text: str) -> Optional[dict]:
    # Strip markdown code blocks if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


def _validate_ai_data(data: dict) -> dict:
    resumen = str(data.get("resumen", "")).strip() or "No summary available."
    categoria = data.get("categoria", "Industria")
    if categoria not in VALID_CATEGORIES:
        categoria = "Industria"
    try:
        relevancia = int(data.get("relevancia", 5))
        relevancia = max(1, min(10, relevancia))
    except (ValueError, TypeError):
        relevancia = 5
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t).strip() for t in tags if str(t).strip()][:5]
    if not tags:
        tags = ["AI"]
    return {"resumen": resumen, "categoria": categoria, "relevancia": relevancia, "tags": tags}


def _call_groq(prompt: str, retries: int = 3) -> Optional[dict]:
    if not GROQ_API_KEY:
        return None

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        logger.error("groq package not installed")
        return None

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=512,
            )
            text = response.choices[0].message.content
            data = _parse_ai_response(text)
            if data:
                return data
            logger.debug("Groq returned unparseable JSON (attempt %d): %s", attempt + 1, text[:200])
        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str or "429" in error_str:
                wait = 2 ** attempt
                logger.info("Groq rate limit, waiting %ds...", wait)
                time.sleep(wait)
            else:
                logger.warning("Groq API error (attempt %d): %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(1)

    return None


def _call_gemini(prompt: str, retries: int = 2) -> Optional[dict]:
    if not GEMINI_API_KEY:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
    except ImportError:
        logger.error("google-generativeai package not installed")
        return None

    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

    for attempt in range(retries):
        try:
            response = model.generate_content(
                full_prompt,
                generation_config={"temperature": 0.2, "max_output_tokens": 512},
            )
            text = response.text
            data = _parse_ai_response(text)
            if data:
                return data
            logger.debug("Gemini returned unparseable JSON (attempt %d): %s", attempt + 1, text[:200])
        except Exception as e:
            logger.warning("Gemini API error (attempt %d): %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2)

    return None


def _fallback_result(item: EnrichedItem) -> AIResult:
    snippet = (item.full_text or item.description)[:200]
    return AIResult(
        resumen=snippet,
        categoria="Industria",
        relevancia=5,
        tags=["AI"],
        provider="fallback",
    )


def enrich_item(item: EnrichedItem, force_provider: Optional[str] = None) -> AIResult:
    prompt = _build_prompt(item)

    if force_provider != "gemini":
        data = _call_groq(prompt)
        if data:
            validated = _validate_ai_data(data)
            return AIResult(**validated, provider="groq")

    data = _call_gemini(prompt)
    if data:
        validated = _validate_ai_data(data)
        return AIResult(**validated, provider="gemini")

    logger.warning("Both AI providers failed for: %s", item.url)
    return _fallback_result(item)


def enrich_all(items: List[EnrichedItem]) -> List[ProcessedItem]:
    processed = []
    groq_count = 0
    gemini_count = 0
    fallback_count = 0
    consecutive_groq_failures = 0
    force_gemini = False

    for item in items:
        provider = "gemini" if force_gemini else None
        result = enrich_item(item, force_provider=provider)

        if result.provider == "groq":
            groq_count += 1
            consecutive_groq_failures = 0
        elif result.provider == "gemini":
            gemini_count += 1
            if not force_gemini:
                consecutive_groq_failures += 1
                if consecutive_groq_failures >= 3:
                    logger.warning("Groq failed 3 times consecutively — switching to Gemini for remaining items")
                    force_gemini = True
        else:
            fallback_count += 1
            consecutive_groq_failures += 1
            if consecutive_groq_failures >= 3:
                force_gemini = True

        processed.append(ProcessedItem(
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            description=item.description,
            source_name=item.source_name,
            language=item.language,
            default_type=item.default_type,
            full_text=item.full_text,
            resumen=result.resumen,
            categoria=result.categoria,
            relevancia=result.relevancia,
            tags=result.tags,
            ai_provider=result.provider,
        ))

        # Small delay to respect Groq's 30 req/min limit
        time.sleep(0.5)

    logger.info(
        "AI enrichment done: Groq=%d Gemini=%d Fallback=%d",
        groq_count, gemini_count, fallback_count
    )
    return processed
