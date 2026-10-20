from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import Base, Category, InventoryItem
from app.services.copilot_service import (
    ask_inventory_copilot,
    get_category_breakdown,
    get_critical_stock_alerts,
    query_inventory_overview,
    search_inventory_items,
)
from app.services.embedding_service import generate_item_text


@pytest.fixture
def rag_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()

    # Seed categories and products
    cat_hardware = Category(name="Hardware")
    cat_audio = Category(name="Audio")
    session.add_all([cat_hardware, cat_audio])
    session.flush()

    item1 = InventoryItem(
        sku="SKU-HW-01",
        name="Mechanical Gaming Keyboard",
        category_id=cat_hardware.id,
        stock_quantity=20,
        unit_price=Decimal("120.00"),
        embedding=None,
    )
    item2 = InventoryItem(
        sku="SKU-HW-02",
        name="Wireless Ergonomic Mouse",
        category_id=cat_hardware.id,
        stock_quantity=3,  # Low stock
        unit_price=Decimal("45.50"),
        embedding=None,
    )
    item3 = InventoryItem(
        sku="SKU-AU-01",
        name="Noise Canceling Headphones",
        category_id=cat_audio.id,
        stock_quantity=0,  # Out of stock
        unit_price=Decimal("250.00"),
        embedding=None,
    )
    session.add_all([item1, item2, item3])
    session.commit()

    yield session
    session.close()


def test_generate_item_text_formatting():
    # 1. Standard full formatting
    text = generate_item_text("Pro Laptop 16", "Laptops", "SKU-LAP-16")
    assert text == "Product: Pro Laptop 16 | Category: Laptops | SKU: SKU-LAP-16"

    # 2. Leading/trailing whitespace stripping
    text_whitespace = generate_item_text("  USB Dock  ", "  Peripherals  ", " SKU-DOCK-99 ")
    assert text_whitespace == "Product: USB Dock | Category: Peripherals | SKU: SKU-DOCK-99"

    # 3. Handling None and empty strings
    text_empty = generate_item_text(None, "Gadgets", "")
    assert text_empty == "Product:  | Category: Gadgets | SKU: "


def test_semantic_similarity_search_query_construction(rag_db):
    # 1. Text fallback query search
    results = search_inventory_items(rag_db, query="Keyboard", limit=5)
    assert len(results) == 1
    assert results[0]["sku"] == "SKU-HW-01"
    assert results[0]["name"] == "Mechanical Gaming Keyboard"
    assert results[0]["category"] == "Hardware"
    assert "unit_price" in results[0]

    # 2. Multi-word phrase search falling back to keyword tokens
    token_results = search_inventory_items(rag_db, query="find ergonomic mouse products", limit=5)
    assert len(token_results) >= 1
    assert any(r["sku"] == "SKU-HW-02" for r in token_results)

    # 3. Category scoped search
    cat_results = search_inventory_items(rag_db, query="", category="Audio", limit=5)
    assert len(cat_results) == 1
    assert cat_results[0]["sku"] == "SKU-AU-01"


def test_tool_calling_functions_return_valid_records(rag_db):
    # 1. query_inventory_overview tool
    overview = query_inventory_overview(rag_db)
    assert isinstance(overview, dict)
    assert overview["total_skus"] == 3
    assert overview["total_units"] == 23  # 20 + 3 + 0
    # 20*120 + 3*45.50 + 0 = 2400 + 136.50 = 2536.50
    assert overview["valuation"] == "2536.50"
    assert overview["low_stock_items"] == 2  # stock 3 and 0
    assert overview["out_of_stock_items"] == 1  # stock 0

    # 2. search_inventory_items tool
    search_data = search_inventory_items(rag_db, query="Headphones", limit=10)
    assert isinstance(search_data, list)
    assert len(search_data) == 1
    item = search_data[0]
    assert item["sku"] == "SKU-AU-01"
    assert item["stock_quantity"] == 0
    assert item["category"] == "Audio"

    # 3. get_critical_stock_alerts tool
    alerts = get_critical_stock_alerts(rag_db, threshold=10)
    assert isinstance(alerts, list)
    assert len(alerts) == 2
    # Verify ordering: lowest stock first
    assert alerts[0]["sku"] == "SKU-AU-01"
    assert alerts[0]["status"] == "OUT_OF_STOCK"
    assert alerts[1]["sku"] == "SKU-HW-02"
    assert alerts[1]["status"] == "LOW_STOCK"

    # 4. get_category_breakdown tool
    breakdown = get_category_breakdown(rag_db)
    assert isinstance(breakdown, list)
    assert len(breakdown) == 2
    cat_map = {b["category"]: b for b in breakdown}
    assert "Hardware" in cat_map
    assert cat_map["Hardware"]["sku_count"] == 2
    assert cat_map["Hardware"]["total_units"] == 23


def test_copilot_fallback_when_credentials_missing(rag_db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "")

    # 1. Overview query fallback
    res_ov = ask_inventory_copilot(rag_db, "What is our overall inventory valuation?")
    assert res_ov["tool_used"] == "query_inventory_overview"
    assert "Live Inventory Overview" in res_ov["response"]
    assert "2,536.50" in res_ov["response"]
    assert len(res_ov["data_sources"]) == 1

    # 2. Critical stock alerts query fallback
    res_alert = ask_inventory_copilot(rag_db, "Check for critical low stockout risks")
    assert res_alert["tool_used"] == "get_critical_stock_alerts"
    assert "critical stock alert(s)" in res_alert["response"]
    assert len(res_alert["data_sources"]) == 2

    # 3. Category breakdown query fallback
    res_cat = ask_inventory_copilot(rag_db, "Show valuation breakdown by category")
    assert res_cat["tool_used"] == "get_category_breakdown"
    assert "Category Breakdown" in res_cat["response"]
    assert len(res_cat["data_sources"]) == 2

    # 4. Specific product search fallback
    res_search = ask_inventory_copilot(rag_db, "Do we have any keyboard items?")
    assert res_search["tool_used"] == "search_inventory_items"
    assert "Mechanical Gaming Keyboard" in res_search["response"]
    assert len(res_search["data_sources"]) >= 1
