import json
import logging
import re
from decimal import Decimal
from typing import Any

from google import genai
from google.genai import types
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Category, InventoryItem
from app.services.embedding_service import generate_embedding

logger = logging.getLogger(__name__)


def parse_search_intent(query: str) -> dict[str, Any]:
    """
    Extract clean search query, price constraints (min_price, max_price),
    and remove conversational and quality filler words.
    """
    clean = (query or "").strip()
    # Strip terminal and conversational punctuation
    clean = re.sub(r"[?!,;:]+", " ", clean).strip()

    max_price: float | None = None
    min_price: float | None = None

    # Match price upper-bound: e.g. "under 100", "below ₹1500", "< 50", "less than $200"
    under_match = re.search(
        r'\b(?:under|below|less than|up to|<|<=)\s*(?:rs\.?|inr|usd)?\s*[\$₹€£]?\s*([0-9]+(?:\.[0-9]+)?)',
        clean,
        re.IGNORECASE,
    )
    if under_match:
        try:
            max_price = float(under_match.group(1))
            clean = clean[:under_match.start()] + " " + clean[under_match.end():]
        except Exception:
            pass

    # Match price lower-bound: e.g. "above 50", "over $20", "> 100", "more than ₹500"
    over_match = re.search(
        r'\b(?:above|over|more than|>|>=)\s*(?:rs\.?|inr|usd)?\s*[\$₹€£]?\s*([0-9]+(?:\.[0-9]+)?)',
        clean,
        re.IGNORECASE,
    )
    if over_match:
        try:
            min_price = float(over_match.group(1))
            clean = clean[:over_match.start()] + " " + clean[over_match.end():]
        except Exception:
            pass

    # Clean conversational prefixes repeatedly
    prefixes = [
        "find me a ", "find me an ", "find me ", "find a ", "find an ", "find ",
        "search for a ", "search for an ", "search for ", "search ",
        "show me a ", "show me an ", "show me ", "look for a ", "look for an ", "look for ",
        "do we have any ", "do we have a ", "do we have an ", "do we have ",
        "do you have any ", "do you have a ", "do you have an ", "do you have ",
        "give me a ", "give me an ", "give me ", "get me a ", "get me an ", "get me ",
        "can you find ", "are there any ", "is there any ", "tell me about "
    ]
    changed = True
    while changed:
        changed = False
        clean_strip = clean.strip()
        for p in prefixes:
            if clean_strip.lower().startswith(p):
                clean = clean_strip[len(p):].strip()
                changed = True
                break

    # Clean conversational suffixes
    suffixes = [
        " products", " product", " items", " item", " in stock", " please",
        " available", " catalog", " list"
    ]
    changed = True
    while changed:
        changed = False
        clean_strip = clean.strip()
        for s in suffixes:
            if clean_strip.lower().endswith(s):
                clean = clean_strip[:-len(s)].strip()
                changed = True
                break

    # Strip subjective quality adjectives and filler words from search keywords
    filler_words = {
        "good", "best", "great", "nice", "top", "cheap", "affordable", "expensive",
        "premium", "some", "any", "all", "our", "the", "a", "an", "items", "item", "products", "product"
    }
    tokens = clean.split()
    meaningful = [t for t in tokens if t.lower() not in filler_words and not t.isdigit()]

    clean_keyword = " ".join(meaningful).strip()

    return {
        "clean_query": clean_keyword or clean.strip(),
        "max_price": max_price,
        "min_price": min_price,
    }


def query_inventory_overview(db: Session) -> dict[str, Any]:
    """Returns live total_skus, valuation, low_stock_items, out_of_stock_items."""
    total_skus = db.scalar(select(func.count(InventoryItem.id))) or 0
    total_units = db.scalar(select(func.coalesce(func.sum(InventoryItem.stock_quantity), 0))) or 0
    raw_valuation = db.scalar(
        select(func.coalesce(func.sum(InventoryItem.stock_quantity * InventoryItem.unit_price), 0))
    ) or Decimal("0.00")
    low_stock_items = db.scalar(
        select(func.count(InventoryItem.id)).where(InventoryItem.stock_quantity < 10)
    ) or 0
    out_of_stock_items = db.scalar(
        select(func.count(InventoryItem.id)).where(InventoryItem.stock_quantity == 0)
    ) or 0

    return {
        "total_skus": total_skus,
        "total_units": total_units,
        "valuation": f"{float(raw_valuation):.2f}",
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
    }


def search_inventory_items(
    db: Session,
    query: str,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 10,
    min_similarity: float = 0.55,
) -> list[dict[str, Any]]:
    """
    Executes precision hybrid vector and text search with price constraints
    and similarity thresholding.
    """
    intent = parse_search_intent(query)
    clean_q = intent["clean_query"]
    if max_price is None:
        max_price = intent.get("max_price")
    if min_price is None:
        min_price = intent.get("min_price")

    items_by_sku: dict[str, dict[str, Any]] = {}

    # 1. Vector semantic search if PostgreSQL and clean query exists
    if clean_q and db.bind and db.bind.dialect.name == "postgresql":
        try:
            vector = generate_embedding(clean_q)
            if vector is not None:
                stmt = (
                    select(
                        InventoryItem,
                        Category.name.label("category_name"),
                        InventoryItem.embedding.cosine_distance(vector).label("distance"),
                    )
                    .outerjoin(Category, InventoryItem.category_id == Category.id)
                    .where(InventoryItem.embedding.is_not(None))
                )
                if category and category.strip():
                    stmt = stmt.where(Category.name.ilike(f"%{category.strip()}%"))
                if max_price is not None:
                    stmt = stmt.where(InventoryItem.unit_price <= Decimal(str(max_price)))
                if min_price is not None:
                    stmt = stmt.where(InventoryItem.unit_price >= Decimal(str(min_price)))

                stmt = stmt.order_by(InventoryItem.embedding.cosine_distance(vector)).limit(limit * 2)
                rows = db.execute(stmt).all()
                for row in rows:
                    sim = round(max(0.0, 1.0 - float(row.distance)), 4)
                    # Filter out low similarity items to ensure strict query relevance
                    if sim >= min_similarity:
                        items_by_sku[row.InventoryItem.sku] = {
                            "id": row.InventoryItem.id,
                            "sku": row.InventoryItem.sku,
                            "name": row.InventoryItem.name,
                            "category": row.category_name or "Uncategorized",
                            "stock_quantity": row.InventoryItem.stock_quantity,
                            "unit_price": str(row.InventoryItem.unit_price),
                            "similarity_score": sim,
                            "search_type": "vector",
                        }
                    if len(items_by_sku) >= limit:
                        break
        except Exception as exc:
            logger.warning("Vector search in hybrid query encountered an error: %s", exc)

    # 2. Precision text-based search (ilike)
    remaining_limit = limit - len(items_by_sku)
    if remaining_limit > 0:
        base_stmt = (
            select(InventoryItem, Category.name.label("category_name"))
            .outerjoin(Category, InventoryItem.category_id == Category.id)
        )
        if category and category.strip():
            base_stmt = base_stmt.where(Category.name.ilike(f"%{category.strip()}%"))
        if max_price is not None:
            base_stmt = base_stmt.where(InventoryItem.unit_price <= Decimal(str(max_price)))
        if min_price is not None:
            base_stmt = base_stmt.where(InventoryItem.unit_price >= Decimal(str(min_price)))

        # Case A: If query is empty, but category or price constraints are set, return matching catalog items
        if not clean_q:
            if (category and category.strip()) or max_price is not None or min_price is not None:
                stmt_filter = base_stmt.order_by(InventoryItem.sku).limit(remaining_limit)
                for row in db.execute(stmt_filter).all():
                    if row.InventoryItem.sku not in items_by_sku:
                        items_by_sku[row.InventoryItem.sku] = {
                            "id": row.InventoryItem.id,
                            "sku": row.InventoryItem.sku,
                            "name": row.InventoryItem.name,
                            "category": row.category_name or "Uncategorized",
                            "stock_quantity": row.InventoryItem.stock_quantity,
                            "unit_price": str(row.InventoryItem.unit_price),
                            "similarity_score": 1.0,
                            "search_type": "category_filter",
                        }
                    if len(items_by_sku) >= limit:
                        break
        else:
            # Case B: Try phrase match on product name or exact SKU match
            phrase_pat = f"%{clean_q}%"
            stmt_phrase = base_stmt.where(
                InventoryItem.name.ilike(phrase_pat) | (InventoryItem.sku.ilike(clean_q))
            ).order_by(InventoryItem.sku).limit(remaining_limit)
            for row in db.execute(stmt_phrase).all():
                if row.InventoryItem.sku not in items_by_sku:
                    items_by_sku[row.InventoryItem.sku] = {
                        "id": row.InventoryItem.id,
                        "sku": row.InventoryItem.sku,
                        "name": row.InventoryItem.name,
                        "category": row.category_name or "Uncategorized",
                        "stock_quantity": row.InventoryItem.stock_quantity,
                        "unit_price": str(row.InventoryItem.unit_price),
                        "similarity_score": 1.0,
                        "search_type": "text",
                    }
                if len(items_by_sku) >= limit:
                    break

            # Case C: Multi-token match: require ALL non-numeric tokens to appear in product name
            remaining_limit = limit - len(items_by_sku)
            if remaining_limit > 0 and " " in clean_q:
                tokens = [t for t in clean_q.split() if len(t) > 2 and not t.isdigit()]
                if tokens:
                    token_conditions = [InventoryItem.name.ilike(f"%{t}%") for t in tokens]
                    stmt_tokens = base_stmt.where(*token_conditions).order_by(InventoryItem.sku).limit(remaining_limit)
                    for row in db.execute(stmt_tokens).all():
                        if row.InventoryItem.sku not in items_by_sku:
                            items_by_sku[row.InventoryItem.sku] = {
                                "id": row.InventoryItem.id,
                                "sku": row.InventoryItem.sku,
                                "name": row.InventoryItem.name,
                                "category": row.category_name or "Uncategorized",
                                "stock_quantity": row.InventoryItem.stock_quantity,
                                "unit_price": str(row.InventoryItem.unit_price),
                                "similarity_score": 1.0,
                                "search_type": "text_keyword",
                            }
                        if len(items_by_sku) >= limit:
                            break

    return list(items_by_sku.values())[:limit]


def get_critical_stock_alerts(db: Session, threshold: int = 10) -> list[dict[str, Any]]:
    """Returns urgent stock-out risks."""
    stmt = (
        select(InventoryItem, Category.name.label("category_name"))
        .outerjoin(Category, InventoryItem.category_id == Category.id)
        .where(InventoryItem.stock_quantity < threshold)
        .order_by(InventoryItem.stock_quantity.asc())
        .limit(50)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "sku": row.InventoryItem.sku,
            "name": row.InventoryItem.name,
            "category": row.category_name or "Uncategorized",
            "stock_quantity": row.InventoryItem.stock_quantity,
            "unit_price": str(row.InventoryItem.unit_price),
            "status": "OUT_OF_STOCK" if row.InventoryItem.stock_quantity == 0 else "LOW_STOCK",
        }
        for row in rows
    ]


def get_category_breakdown(db: Session) -> list[dict[str, Any]]:
    """Returns valuation per category."""
    stmt = (
        select(
            func.coalesce(Category.name, "Uncategorized").label("category"),
            func.count(InventoryItem.id).label("sku_count"),
            func.coalesce(func.sum(InventoryItem.stock_quantity), 0).label("total_units"),
            func.coalesce(
                func.sum(InventoryItem.stock_quantity * InventoryItem.unit_price), Decimal("0.00")
            ).label("category_valuation"),
        )
        .select_from(InventoryItem)
        .outerjoin(Category, InventoryItem.category_id == Category.id)
        .group_by(Category.name)
        .order_by(func.sum(InventoryItem.stock_quantity * InventoryItem.unit_price).desc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "category": row.category,
            "sku_count": row.sku_count,
            "total_units": row.total_units,
            "valuation": f"{float(row.category_valuation):.2f}",
        }
        for row in rows
    ]


# Deterministic formatting helpers for fallback
def _format_overview_response(data: dict[str, Any]) -> str:
    total_skus = data.get("total_skus", 0)
    total_units = data.get("total_units", 0)
    valuation = data.get("valuation", "0.00")
    low_stock = data.get("low_stock_items", 0)
    out_of_stock = data.get("out_of_stock_items", 0)
    return (
        f"Live Inventory Overview:\n"
        f"• Total Catalog SKUs: {total_skus}\n"
        f"• Total Stocked Units: {total_units:,}\n"
        f"• Aggregate Inventory Valuation: ${float(valuation):,.2f}\n"
        f"• Low-Stock Alerts (<10 units): {low_stock}\n"
        f"• Out-of-Stock Items: {out_of_stock}\n\n"
        + (
            f"⚠️ Operational Alert: {out_of_stock} item(s) are completely out of stock and require immediate restocking."
            if out_of_stock > 0
            else "✅ Stock levels are healthy across the catalog."
        )
    )


def _format_alerts_response(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "No critical stock alerts found. All inventory items currently meet healthy stock thresholds."
    lines = [f"Found {len(alerts)} critical stock alert(s):"]
    for a in alerts[:15]:
        status_icon = "🔴 OUT OF STOCK" if a.get("stock_quantity", 0) == 0 else "🟡 LOW STOCK"
        lines.append(
            f"• [{status_icon}] {a.get('name')} (SKU: {a.get('sku')}) — "
            f"Stock: {a.get('stock_quantity')} units | Unit Price: ${float(a.get('unit_price', 0)):.2f} | Category: {a.get('category')}"
        )
    return "\n".join(lines)


def _format_category_response(cats: list[dict[str, Any]]) -> str:
    if not cats:
        return "No inventory categories found in the database."
    total_val = sum(float(c.get("valuation", 0)) for c in cats)
    lines = [f"Inventory Category Breakdown (Total Valuation: ${total_val:,.2f}):"]
    for c in cats:
        lines.append(
            f"• {c.get('category')}: {c.get('sku_count')} SKUs, {c.get('total_units'):,} units, "
            f"Valuation: ${float(c.get('valuation', 0)):,.2f}"
        )
    return "\n".join(lines)


def _format_search_response(items: list[dict[str, Any]], query: str, intent: dict[str, Any] | None = None) -> str:
    price_constraints = []
    if intent:
        if intent.get("max_price") is not None:
            price_constraints.append(f"unit price <= ${intent['max_price']:.2f}")
        if intent.get("min_price") is not None:
            price_constraints.append(f"unit price >= ${intent['min_price']:.2f}")
    constraint_str = f" ({', '.join(price_constraints)})" if price_constraints else ""

    if not items:
        return f"No inventory products found matching '{query}'{constraint_str}. Try searching by alternative keywords or category."
    lines = [f"Found {len(items)} product(s) matching '{query}'{constraint_str}:"]
    for item in items:
        sim = item.get("similarity_score")
        sim_badge = f" [Vector Match: {int(sim * 100)}%]" if sim is not None and sim < 1.0 else ""
        lines.append(
            f"• {item.get('name')} (SKU: {item.get('sku')} | Category: {item.get('category')}): "
            f"{item.get('stock_quantity')} units in stock at ${float(item.get('unit_price', 0)):.2f}{sim_badge}"
        )
    return "\n".join(lines)


def _execute_deterministic_query(db: Session, user_query: str) -> dict[str, Any]:
    """Execute keyword-matched read-only database query when Gemini is unconfigured or unavailable."""
    q_lower = user_query.lower()

    # 1. Stock alerts / stockout checks
    if any(k in q_lower for k in ["alert", "out of stock", "low stock", "low in stock", "stockout", "shortage", "urgent", "critical"]):
        tool_used = "get_critical_stock_alerts"
        data = get_critical_stock_alerts(db)
        response_text = _format_alerts_response(data)
        return {
            "response": response_text,
            "tool_used": tool_used,
            "data_sources": data,
        }

    # 2. Category distribution / breakdown checks
    if any(k in q_lower for k in ["category", "categories", "breakdown", "department", "by category"]):
        tool_used = "get_category_breakdown"
        data = get_category_breakdown(db)
        response_text = _format_category_response(data)
        return {
            "response": response_text,
            "tool_used": tool_used,
            "data_sources": data,
        }

    # 3. Catalog overview / aggregate valuation checks
    if any(k in q_lower for k in ["overview", "valuation", "total", "worth", "summary", "how many items", "how many skus", "metrics", "stats"]):
        tool_used = "query_inventory_overview"
        data = query_inventory_overview(db)
        response_text = _format_overview_response(data)
        return {
            "response": response_text,
            "tool_used": tool_used,
            "data_sources": [data],
        }

    # 4. Default to hybrid product search with intent parsing
    intent = parse_search_intent(user_query)
    clean_search = intent["clean_query"]
    min_price = intent.get("min_price")
    max_price = intent.get("max_price")

    tool_used = "search_inventory_items"
    data = search_inventory_items(
        db,
        query=clean_search or user_query,
        min_price=min_price,
        max_price=max_price,
        limit=10,
    )
    response_text = _format_search_response(data, user_query, intent=intent)
    return {
        "response": response_text,
        "tool_used": tool_used,
        "data_sources": data,
    }


def ask_inventory_copilot(
    db: Session,
    user_query: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Enterprise-grade inventory copilot using Gemini Function Calling and PostgreSQL.
    Binds read-only tools, executes live DB queries, and synthesizes grounded business responses.
    Gracefully falls back to deterministic keyword matching if GEMINI_API_KEY is missing or errors occur.
    """
    settings = get_settings()
    api_key = settings.gemini_api_key.strip() if settings.gemini_api_key else ""

    if not api_key:
        logger.info("GEMINI_API_KEY is not configured; executing deterministic copilot engine.")
        return _execute_deterministic_query(db, user_query)

    try:
        client = genai.Client(api_key=api_key)

        # Tool wrappers without db parameter for Gemini function declaration
        def tool_query_overview() -> dict[str, Any]:
            """Retrieve live high-level inventory metrics: total SKUs, total units, valuation, low-stock and out-of-stock count."""
            return query_inventory_overview(db)

        def tool_search_items(
            query: str,
            category: str = "",
            min_price: float | None = None,
            max_price: float | None = None,
            limit: int = 10,
        ) -> list[dict[str, Any]]:
            """Search inventory products by name, SKU, or category with optional price bounds."""
            return search_inventory_items(
                db,
                query=query,
                category=category or None,
                min_price=min_price,
                max_price=max_price,
                limit=limit,
            )

        def tool_critical_alerts(threshold: int = 10) -> list[dict[str, Any]]:
            """Retrieve critical low-stock and out-of-stock risk alerts."""
            return get_critical_stock_alerts(db, threshold=threshold)

        def tool_category_breakdown() -> list[dict[str, Any]]:
            """Retrieve catalog valuation and inventory quantities broken down by product category."""
            return get_category_breakdown(db)

        tool_map = {
            "tool_query_overview": ("query_inventory_overview", tool_query_overview),
            "tool_search_items": ("search_inventory_items", tool_search_items),
            "tool_critical_alerts": ("get_critical_stock_alerts", tool_critical_alerts),
            "tool_category_breakdown": ("get_category_breakdown", tool_category_breakdown),
        }

        tools_list = [
            tool_query_overview,
            tool_search_items,
            tool_critical_alerts,
            tool_category_breakdown,
        ]

        system_instruction = (
            "You are an enterprise AI inventory copilot for OmniFeed. "
            "You have access to live database tools to inspect inventory metrics, search products, check stockout risks, and analyze categories. "
            "Always call the most relevant tool to retrieve facts before formulating your response. "
            "Ground your answer strictly in the data returned by the tool."
        )

        model_name = "gemini-3.5-flash"

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools_list,
            temperature=0.0,
        )

        # Build contents including optional chat history
        contents: list[Any] = []
        if chat_history:
            for msg in chat_history[-6:]:
                role = msg.get("role", "user")
                content_text = msg.get("content", "")
                if content_text:
                    contents.append(f"{role.capitalize()}: {content_text}")
        contents.append(f"User: {user_query}")

        prompt_str = "\n".join(str(c) for c in contents)

        response = client.models.generate_content(
            model=model_name,
            contents=prompt_str,
            config=config,
        )

        # Check if the model called a tool
        if response and response.function_calls:
            fc = response.function_calls[0]
            fc_name = fc.name
            fc_args = fc.args or {}

            if fc_name in tool_map:
                tool_label, tool_func = tool_map[fc_name]
                # Execute tool with DB session
                if fc_name == "tool_search_items":
                    user_intent = parse_search_intent(user_query)
                    t_min = fc_args.get("min_price")
                    if t_min is None:
                        t_min = user_intent.get("min_price")
                    t_max = fc_args.get("max_price")
                    if t_max is None:
                        t_max = user_intent.get("max_price")

                    tool_data = tool_func(
                        query=fc_args.get("query", user_query),
                        category=fc_args.get("category", ""),
                        min_price=float(t_min) if t_min is not None else None,
                        max_price=float(t_max) if t_max is not None else None,
                        limit=int(fc_args.get("limit", 10)),
                    )
                elif fc_name == "tool_critical_alerts":
                    tool_data = tool_func(threshold=int(fc_args.get("threshold", 10)))
                else:
                    tool_data = tool_func()

                data_sources = tool_data if isinstance(tool_data, list) else [tool_data]

                # Synthesize grounded answer
                synthesis_prompt = (
                    f"User Inquiry: {user_query}\n\n"
                    f"Database Function Executed: {tool_label}\n"
                    f"Live Database Output:\n{json.dumps(tool_data, indent=2, default=str)}\n\n"
                    "Formulate a clear, direct, professional business response grounded strictly in the live database output above."
                )

                synthesis_resp = client.models.generate_content(
                    model=model_name,
                    contents=synthesis_prompt,
                )

                if synthesis_resp and synthesis_resp.text:
                    return {
                        "response": synthesis_resp.text.strip(),
                        "tool_used": tool_label,
                        "data_sources": data_sources,
                    }

                # If synthesis returned empty text, format deterministically
                if tool_label == "query_inventory_overview":
                    resp_text = _format_overview_response(tool_data)
                elif tool_label == "get_critical_stock_alerts":
                    resp_text = _format_alerts_response(tool_data)
                elif tool_label == "get_category_breakdown":
                    resp_text = _format_category_response(tool_data)
                else:
                    resp_text = _format_search_response(tool_data, user_query, intent=parse_search_intent(user_query))

                return {
                    "response": resp_text,
                    "tool_used": tool_label,
                    "data_sources": data_sources,
                }

        # If the model answered directly without a function call, ensure response is grounded in database
        grounded = _execute_deterministic_query(db, user_query)
        if grounded.get("tool_used"):
            return grounded

        if response and response.text:
            return {
                "response": response.text.strip(),
                "tool_used": None,
                "data_sources": [],
            }

        return grounded

    except Exception as exc:
        logger.warning("Gemini Copilot encountered an error (%s); falling back to deterministic database query.", exc)
        return _execute_deterministic_query(db, user_query)
