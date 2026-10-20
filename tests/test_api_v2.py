from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, Category, IngestionError, IngestionJob, InventoryItem, get_db
from app.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_api_v2_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def seed_catalog():
    db = TestingSessionLocal()
    cat = Category(name="Peripherals")
    db.add(cat)
    db.flush()

    item1 = InventoryItem(
        sku="SKU-KEY-10",
        name="Wireless Mechanical Keyboard",
        category_id=cat.id,
        stock_quantity=18,
        unit_price=Decimal("129.99"),
    )
    item2 = InventoryItem(
        sku="SKU-MOU-20",
        name="RGB Gaming Mouse",
        category_id=cat.id,
        stock_quantity=4,
        unit_price=Decimal("59.99"),
    )
    db.add_all([item1, item2])
    db.commit()
    db.close()


def test_post_ai_ask_endpoint(api_client, seed_catalog):
    # 1. Ask Overview
    payload_overview = {
        "query": "What is our current inventory valuation?",
        "history": [],
    }
    resp = api_client.post("/api/v1/ai/ask", json=payload_overview)
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert data["tool_used"] == "query_inventory_overview"
    assert isinstance(data["data_sources"], list)
    assert len(data["data_sources"]) > 0

    # 2. Ask Stock Alerts
    payload_alerts = {
        "query": "Which products have critical low stock alerts?",
        "history": [{"role": "user", "content": "hello"}],
    }
    resp_alerts = api_client.post("/api/v1/ai/ask", json=payload_alerts)
    assert resp_alerts.status_code == 200
    data_alerts = resp_alerts.json()
    assert data_alerts["tool_used"] == "get_critical_stock_alerts"
    assert len(data_alerts["data_sources"]) == 1
    assert data_alerts["data_sources"][0]["sku"] == "SKU-MOU-20"

    # 3. Test empty query rejection
    bad_payload = {"query": "   ", "history": []}
    bad_resp = api_client.post("/api/v1/ai/ask", json=bad_payload)
    assert bad_resp.status_code == 400
    assert "Query cannot be empty" in bad_resp.json()["detail"]


def test_post_ai_ask_with_mocked_gemini(api_client, seed_catalog, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "mock_key")

    mock_fc = MagicMock()
    mock_fc.name = "tool_query_overview"
    mock_fc.args = {}

    first_response = MagicMock()
    first_response.function_calls = [mock_fc]
    first_response.text = None

    second_response = MagicMock()
    second_response.text = "Copilot executive response: Portfolio is healthy."

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [first_response, second_response]
        mock_client_cls.return_value = mock_client

        resp = api_client.post("/api/v1/ai/ask", json={"query": "Inventory status summary", "history": []})
        assert resp.status_code == 200
        result = resp.json()
        assert result["tool_used"] == "query_inventory_overview"
        assert result["response"] == "Copilot executive response: Portfolio is healthy."


def test_get_items_search_semantic_endpoint_structure(api_client, seed_catalog):
    # 1. Successful semantic search structure
    resp = api_client.get("/api/v1/items/search-semantic?query=Keyboard&limit=10")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1

    item = items[0]
    expected_keys = {
        "id",
        "sku",
        "name",
        "category",
        "stock_quantity",
        "unit_price",
        "similarity_score",
        "search_type",
    }
    assert expected_keys.issubset(set(item.keys()))
    assert item["sku"] == "SKU-KEY-10"
    assert item["name"] == "Wireless Mechanical Keyboard"
    assert item["category"] == "Peripherals"

    # 2. Limit parameter validation
    resp_limit = api_client.get("/api/v1/items/search-semantic?query=Gaming&limit=1")
    assert resp_limit.status_code == 200
    assert len(resp_limit.json()) == 1

    # 3. Query required and validation
    resp_empty = api_client.get("/api/v1/items/search-semantic?query=")
    assert resp_empty.status_code == 422


def test_get_export_job_errors_csv_output(api_client):
    db = TestingSessionLocal()
    job = IngestionJob(
        filename="vendor_batch_errors.csv",
        file_type="csv",
        status="completed_with_errors",
        records_processed=15,
        records_inserted=13,
        records_updated=0,
        records_failed=2,
    )
    db.add(job)
    db.flush()

    err1 = IngestionError(
        job_id=job.id,
        row_number=4,
        sku="SKU-ERR-01",
        error_code="VALIDATION_ERROR",
        error_message="unit_price must be greater than zero.",
        raw_record='{"sku":"SKU-ERR-01","unit_price":"-5.00"}',
    )
    err2 = IngestionError(
        job_id=job.id,
        row_number=9,
        sku="SKU-ERR-02",
        error_code="VALIDATION_ERROR",
        error_message="stock_quantity cannot be negative.",
        raw_record='{"sku":"SKU-ERR-02","stock_quantity":"-2"}',
    )
    db.add_all([err1, err2])
    db.commit()
    job_id = job.id
    db.close()

    resp = api_client.get(f"/api/v1/ingestion/jobs/{job_id}/export-errors")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f'filename="ingestion_job_{job_id}_errors.csv"' in resp.headers["content-disposition"]

    csv_text = resp.text
    lines = csv_text.strip().split("\r\n") if "\r\n" in csv_text else csv_text.strip().split("\n")
    assert len(lines) == 3  # Header + 2 error rows
    assert lines[0] == "Row Number,SKU,Error Code,Error Message,Raw Record"
    assert "4,SKU-ERR-01,VALIDATION_ERROR,unit_price must be greater than zero." in lines[1]
    assert "9,SKU-ERR-02,VALIDATION_ERROR,stock_quantity cannot be negative." in lines[2]

    # Test 404 for nonexistent job
    resp_404 = api_client.get("/api/v1/ingestion/jobs/888888/export-errors")
    assert resp_404.status_code == 404
