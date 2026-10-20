import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
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
def setup_database():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "app": "OmniFeed AI",
        "status": "operational",
        "version": "2.1.0",
        "docs": "/docs",
    }


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "total_catalog_items" in data
    assert "timestamp" in data
    assert isinstance(data["total_catalog_items"], int)



def test_ingest_csv_and_overview(client):
    csv_content = (
        b"sku,name,category,stock_quantity,unit_price\n"
        b"SKU-A,Product A,Electronics,20,$10.00\n"
        b"SKU-B,Product B,Electronics,5,$50.00\n"
        b"SKU-C,Product C,Office,0,$15.00\n"
    )

    response = client.post(
        "/api/v1/ingest",
        files={"file": ("test.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["records_processed"] == 3
    assert data["records_inserted"] == 3
    assert data["records_failed"] == 0

    # Overview endpoint test
    overview_resp = client.get("/api/v1/analytics/overview")
    assert overview_resp.status_code == 200
    ov = overview_resp.json()
    assert ov["total_skus"] == 3
    assert ov["total_units"] == 25
    # Valuation: 20*10 + 5*50 + 0*15 = 200 + 250 = 450.00
    assert ov["inventory_valuation"] == "450.00"
    assert ov["low_stock_items"] == 2  # stock 5 and 0
    assert ov["out_of_stock_items"] == 1  # stock 0


def test_items_list_and_filters(client):
    csv_content = (
        b"sku,name,category,stock_quantity,unit_price\n"
        b"SKU-ALPHA,Alpha Keyboard,Accessories,15,$30.00\n"
        b"SKU-BETA,Beta Mouse,Accessories,25,$20.00\n"
        b"SKU-GAMMA,Gamma Monitor,Displays,8,$200.00\n"
    )
    client.post(
        "/api/v1/ingest",
        files={"file": ("items.csv", csv_content, "text/csv")},
    )

    # Search filter
    resp = client.get("/api/v1/items?search=Mouse")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["total"] == 1
    assert res_data["items"][0]["sku"] == "SKU-BETA"

    # Category filter
    resp_cat = client.get("/api/v1/items?category=Displays")
    assert resp_cat.status_code == 200
    assert resp_cat.json()["total"] == 1
    assert resp_cat.json()["items"][0]["sku"] == "SKU-GAMMA"

    # Single item lookup
    resp_single = client.get("/api/v1/items/SKU-ALPHA")
    assert resp_single.status_code == 200
    assert resp_single.json()["name"] == "Alpha Keyboard"

    # Not found single item
    resp_404 = client.get("/api/v1/items/UNKNOWN-SKU")
    assert resp_404.status_code == 404


def test_analytics_categories_and_stock_alerts(client):
    csv_content = (
        b"sku,name,category,stock_quantity,unit_price\n"
        b"SKU-1,Desk,Furniture,12,$100.00\n"
        b"SKU-2,Chair,Furniture,4,$50.00\n"
    )
    client.post(
        "/api/v1/ingest",
        files={"file": ("data.csv", csv_content, "text/csv")},
    )

    # Categories
    resp_cat = client.get("/api/v1/analytics/categories")
    assert resp_cat.status_code == 200
    cats = resp_cat.json()
    assert len(cats) == 1
    assert cats[0]["category"] == "Furniture"
    assert cats[0]["sku_count"] == 2
    assert cats[0]["total_units"] == 16
    assert cats[0]["total_valuation"] == "1400.00"

    # Stock alerts
    resp_alerts = client.get("/api/v1/analytics/stock-alerts?threshold=10")
    assert resp_alerts.status_code == 200
    alerts = resp_alerts.json()
    assert len(alerts) == 1
    assert alerts[0]["sku"] == "SKU-2"


def test_ingestion_history_and_ai_insights(client):
    resp_hist = client.get("/api/v1/ingestion/history")
    assert resp_hist.status_code == 200
    assert "history" in resp_hist.json()

    resp_ai = client.post("/api/v1/ai/insights")
    assert resp_ai.status_code == 200
    insights = resp_ai.json()
    assert "summary" in insights
    assert "recommendations" in insights


def test_ingest_file_size_limit_rejection(client, monkeypatch):
    from app.config import Settings
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(max_upload_mb=0))
    csv_content = b"sku,name,category,stock_quantity,unit_price\nSKU-1,Item,Cat,5,$10.00\n"
    response = client.post(
        "/api/v1/ingest",
        files={"file": ("test.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 413
    assert "File exceeds maximum allowed size" in response.json()["detail"]

