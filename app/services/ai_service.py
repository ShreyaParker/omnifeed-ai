import json
import logging
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger(__name__)


def _rule_based_insights(overview: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic rule-based fallback when Gemini API key is missing or call fails."""
    total_skus = overview.get("total_skus", 0)
    total_units = overview.get("total_units", 0)
    valuation = overview.get("inventory_valuation", "0.00")
    low_stock = overview.get("low_stock_items", 0)
    out_of_stock = overview.get("out_of_stock_items", 0)

    recs: list[str] = []
    if out_of_stock > 0:
        recs.append(
            f"Urgent action required: {out_of_stock} product(s) are completely out of stock. Prioritize immediate replenishment."
        )
    if low_stock > 0:
        recs.append(
            f"Review reorder triggers for {low_stock} product(s) with stock levels below 10 units."
        )
    if alerts:
        top_items = [
            f"{a.get('name', a.get('sku'))} (SKU: {a.get('sku')}, stock: {a.get('stock_quantity')})"
            for a in alerts[:3]
        ]
        recs.append(f"Top critical low-stock items: {', '.join(top_items)}.")
    if not recs:
        recs.append("All inventory items currently meet healthy stock thresholds.")

    summary = (
        f"Inventory catalog contains {total_skus} SKUs with {total_units} total units valued at ${valuation}. "
        f"Currently, {low_stock} items are at or below low-stock threshold, including {out_of_stock} out-of-stock items."
    )

    return {
        "source": "rules",
        "summary": summary,
        "recommendations": recs,
    }


def generate_insights(overview: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Generate inventory operations insights using Google Gemini AI.
    Falls back to a deterministic rule-based analysis if the API key is not configured or if an error occurs.
    """
    settings = get_settings()
    api_key = settings.gemini_api_key.strip()

    if not api_key:
        logger.info("GEMINI_API_KEY is not configured; using rule-based fallback.")
        return _rule_based_insights(overview, alerts)

    try:
        client = genai.Client(api_key=api_key)

        system_instruction = (
            "You are an expert inventory operations analyst. Analyze the provided inventory metrics and low-stock alerts. "
            "Use ONLY the supplied data to produce your analysis without hallucinating or making assumptions beyond the facts. "
            "Return a clean JSON object containing exactly these fields:\n"
            "{\n"
            '  "summary": "<concise executive overview of current stock health, valuation, and risk points>",\n'
            '  "recommendations": ["<actionable recommendation 1>", "<actionable recommendation 2>", ...]\n'
            "}"
        )

        prompt = (
            f"Aggregated Inventory Overview:\n{json.dumps(overview, indent=2, default=str)}\n\n"
            f"Top Low-Stock Alerts:\n{json.dumps(alerts[:10], indent=2, default=str)}\n\n"
            "Provide executive operations insights and recommendations based strictly on the above figures."
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.2,
        )

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
        )

        if response and response.text:
            parsed = json.loads(response.text)
            if isinstance(parsed, dict) and "summary" in parsed and "recommendations" in parsed:
                return {
                    "source": "gemini",
                    "summary": str(parsed["summary"]),
                    "recommendations": [str(r) for r in parsed.get("recommendations", [])],
                }

        logger.warning("Gemini returned unexpected structure; falling back to rule-based engine.")
        return _rule_based_insights(overview, alerts)

    except Exception as exc:
        logger.warning("Gemini AI insights generation encountered an error: %s. Falling back to rule-based engine.", exc)
        return _rule_based_insights(overview, alerts)
