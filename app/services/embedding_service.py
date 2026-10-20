import logging
from typing import Any

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import InventoryItem

logger = logging.getLogger(__name__)


def generate_item_text(name: str, category: str, sku: str) -> str:
    """
    Format a semantic document representation of the product.
    """
    clean_name = (name or "").strip()
    clean_cat = (category or "").strip()
    clean_sku = (sku or "").strip()
    return f"Product: {clean_name} | Category: {clean_cat} | SKU: {clean_sku}"


def generate_embedding(text: str) -> list[float] | None:
    """
    Generate vector embedding using Google GenAI client.
    Returns None if GEMINI_API_KEY is not set or if an error occurs.
    """
    if not text or not text.strip():
        return None

    settings = get_settings()
    api_key = settings.gemini_api_key.strip() if settings.gemini_api_key else ""
    if not api_key:
        logger.info("GEMINI_API_KEY is not configured; skipping embedding generation.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.embed_content(
                model=settings.embedding_model,
                contents=text,
            )
        except Exception:
            # Fallback to gemini-embedding-001 with 768 dimensions matching pgvector column
            response = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=768),
            )

        if response and response.embeddings:
            values = response.embeddings[0].values
            if values is not None:
                return list(values)
        return None
    except Exception as exc:
        logger.warning("Error generating embedding: %s", exc)
        return None


def batch_embed_items(db: Session, limit: int = 50, batch_size: int = 25) -> int:
    """
    Find inventory items where embedding IS NULL, generate their vectors,
    and commit updates in batches.
    """
    try:
        stmt = (
            select(InventoryItem)
            .options(joinedload(InventoryItem.category))
            .where(InventoryItem.embedding.is_(None))
            .limit(limit)
        )
        items = list(db.scalars(stmt).all())
        if not items:
            return 0

        updated_count = 0
        for item in items:
            cat_name = item.category.name if item.category else ""
            text_repr = generate_item_text(name=item.name, category=cat_name, sku=item.sku)
            vector = generate_embedding(text_repr)
            if vector is not None:
                item.embedding = vector
                updated_count += 1
                if updated_count % batch_size == 0:
                    db.commit()

        if updated_count > 0:
            db.commit()

        return updated_count
    except Exception:
        db.rollback()
        raise
