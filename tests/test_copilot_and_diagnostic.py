from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, Category, IngestionError, IngestionJob, InventoryItem, get_db
from app.main import app
from app.services.copilot_service import (
    ask_inventory_copilot,
    get_category_breakdown,
    get_critical_stock_alerts,
    query_inventory_overview,
    search_inventory_items,
)
from app.services.diagnostic_service import generate_supplier_diagnostic

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
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_data():
    db = TestingSessionLocal()
    cat_tech = Category(name="Tech")
    cat_home = Category(name="Home")
    db.add_all([cat_tech, cat_home])
    db.flush()

    item1 = InventoryItem(
        sku="SKU-T1",
        name="Ultra Laptop",
        category_id=cat_tech.id,
        stock_quantity=15,
        unit_price=Decimal("1200.00"),
    )
    item2 = InventoryItem(
        sku="SKU-T2",
        name="Wireless Gaming Mouse",
        category_id=cat_tech.id,
        stock_quantity=2,  # Low stock
        unit_price=Decimal("50.00"),
    )
    item3 = InventoryItem(
        sku="SKU-H1",
        name="Ergonomic Desk Chair",
        category_id=cat_home.id,
        stock_quantity=0,  # Out of stock
        unit_price=Decimal("200.00"),
    )
    db.add_all([item1, item2, item3])
    db.commit()
    db.close()


def test_copilot_database_tools(sample_data):
    db = TestingSessionLocal()
    try:
        # 1. Overview tool
        overview = query_inventory_overview(db)
        assert overview["total_skus"] == 3
        assert overview["total_units"] == 17
        # 15*1200 + 2*50 + 0*200 = 18000 + 100 = 18100.00
        assert overview["valuation"] == "18100.00"
        assert overview["low_stock_items"] == 2
        assert overview["out_of_stock_items"] == 1

        # 2. Critical alerts tool
        alerts = get_critical_stock_alerts(db, threshold=10)
        assert len(alerts) == 2
        assert alerts[0]["sku"] == "SKU-H1"
        assert alerts[0]["status"] == "OUT_OF_STOCK"
        assert alerts[1]["sku"] == "SKU-T2"
        assert alerts[1]["status"] == "LOW_STOCK"

        # 3. Category breakdown tool
        categories = get_category_breakdown(db)
        assert len(categories) == 2
        cat_names = [c["category"] for c in categories]
        assert "Tech" in cat_names
        assert "Home" in cat_names

        # 4. Search tool
        results = search_inventory_items(db, query="Mouse")
        assert len(results) == 1
        assert results[0]["sku"] == "SKU-T2"
    finally:
        db.close()


def test_ask_inventory_copilot_deterministic_fallbacks(sample_data, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "")

    db = TestingSessionLocal()
    try:
        # Overview query
        resp_overview = ask_inventory_copilot(db, "Give me an overview of our inventory valuation")
        assert resp_overview["tool_used"] == "query_inventory_overview"
        assert "Live Inventory Overview" in resp_overview["response"]
        assert len(resp_overview["data_sources"]) == 1

        # Critical alerts query
        resp_alerts = ask_inventory_copilot(db, "Are there any critical stockout alerts?")
        assert resp_alerts["tool_used"] == "get_critical_stock_alerts"
        assert "Found 2 critical stock alert(s)" in resp_alerts["response"]
        assert len(resp_alerts["data_sources"]) == 2

        # Category query
        resp_cat = ask_inventory_copilot(db, "Show me valuation by category breakdown")
        assert resp_cat["tool_used"] == "get_category_breakdown"
        assert "Category Breakdown" in resp_cat["response"]
        assert len(resp_cat["data_sources"]) == 2

        # Search query
        resp_search = ask_inventory_copilot(db, "Find laptop products")
        assert resp_search["tool_used"] == "search_inventory_items"
        assert "Ultra Laptop" in resp_search["response"]
        assert len(resp_search["data_sources"]) >= 1
    finally:
        db.close()


def test_ask_inventory_copilot_gemini_function_calling_mock(sample_data, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "test_key")

    mock_fc = MagicMock()
    mock_fc.name = "tool_query_overview"
    mock_fc.args = {}

    first_response = MagicMock()
    first_response.function_calls = [mock_fc]
    first_response.text = None

    second_response = MagicMock()
    second_response.text = "Grounded analysis: Total catalog contains 3 SKUs valued at $18,100."

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [first_response, second_response]
        mock_client_cls.return_value = mock_client

        db = TestingSessionLocal()
        try:
            result = ask_inventory_copilot(db, "What is our inventory status?")
            assert result["tool_used"] == "query_inventory_overview"
            assert "Grounded analysis" in result["response"]
            assert len(result["data_sources"]) == 1
        finally:
            db.close()


def test_generate_supplier_diagnostic(sample_data, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "")

    db = TestingSessionLocal()
    try:
        # Create an ingestion job with errors
        job = IngestionJob(
            filename="vendor_feed_fail.csv",
            file_type="csv",
            status="completed_with_errors",
            records_processed=10,
            records_inserted=7,
            records_updated=0,
            records_failed=3,
        )
        db.add(job)
        db.flush()

        err1 = IngestionError(
            job_id=job.id,
            row_number=3,
            sku="SKU-DUP",
            error_code="VALIDATION_ERROR",
            error_message="Duplicate SKU 'SKU-DUP' within the uploaded file.",
        )
        err2 = IngestionError(
            job_id=job.id,
            row_number=5,
            sku="SKU-NEG",
            error_code="VALIDATION_ERROR",
            error_message="stock_quantity cannot be negative.",
        )
        err3 = IngestionError(
            job_id=job.id,
            row_number=8,
            sku="SKU-PRICE",
            error_code="VALIDATION_ERROR",
            error_message="Invalid unit_price.",
        )
        db.add_all([err1, err2, err3])
        db.commit()

        diagnostic = generate_supplier_diagnostic(db, job.id)
        assert diagnostic["job_id"] == job.id
        assert diagnostic["health_score"] == 70
        assert diagnostic["records_failed"] == 3
        assert len(diagnostic["root_causes"]) >= 2
        assert len(diagnostic["actionable_vendor_instructions"]) >= 2
        assert len(diagnostic["sample_errors"]) == 3
    finally:
        db.close()


def test_api_ask_copilot_endpoint(client, sample_data):
    payload = {"query": "How many items are low in stock?", "history": []}
    response = client.post("/api/v1/ai/ask", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "tool_used" in data
    assert "data_sources" in data
    assert data["tool_used"] == "get_critical_stock_alerts"

    # Test empty query validation
    bad_resp = client.post("/api/v1/ai/ask", json={"query": "  ", "history": []})
    assert bad_resp.status_code == 400


def test_api_diagnose_endpoint(client):
    db = TestingSessionLocal()
    job = IngestionJob(
        filename="clean_vendor.csv",
        file_type="csv",
        status="completed",
        records_processed=20,
        records_inserted=20,
        records_updated=0,
        records_failed=0,
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    resp = client.post(f"/api/v1/ai/diagnose/{job_id}")
    assert resp.status_code == 200
    diag = resp.json()
    assert diag["job_id"] == job_id
    assert diag["health_score"] == 100
    assert diag["records_failed"] == 0

    # 404 for unknown job
    resp_404 = client.post("/api/v1/ai/diagnose/999999")
    assert resp_404.status_code == 404


def test_api_search_semantic_endpoint(client, sample_data):
    # Tests endpoint and graceful text fallback in SQLite test environment
    response = client.get("/api/v1/items/search-semantic?query=Laptop")
    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 1
    assert results[0]["sku"] == "SKU-T1"
    assert "similarity_score" in results[0]


def test_api_export_job_errors_endpoint(client):
    db = TestingSessionLocal()
    job = IngestionJob(
        filename="supplier_bad.csv",
        file_type="csv",
        status="completed_with_errors",
        records_processed=5,
        records_inserted=3,
        records_updated=0,
        records_failed=2,
    )
    db.add(job)
    db.flush()

    e1 = IngestionError(
        job_id=job.id,
        row_number=2,
        sku="SKU-ERR1",
        error_code="VALIDATION_ERROR",
        error_message="unit_price must be greater than zero.",
        raw_record='{"sku":"SKU-ERR1"}',
    )
    db.add(e1)
    db.commit()
    job_id = job.id
    db.close()

    response = client.get(f"/api/v1/ingestion/jobs/{job_id}/export-errors")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f'filename="ingestion_job_{job_id}_errors.csv"' in response.headers["content-disposition"]
    content = response.text
    assert "Row Number,SKU,Error Code,Error Message,Raw Record" in content
    assert "SKU-ERR1" in content
    assert "unit_price must be greater than zero" in content

    # 404 test
    resp_404 = client.get("/api/v1/ingestion/jobs/999999/export-errors")
    assert resp_404.status_code == 404
