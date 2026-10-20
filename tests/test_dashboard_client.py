import io
from unittest.mock import MagicMock, patch
import pytest
import requests

from dashboard.api_client import (
    ask_copilot,
    diagnose_job,
    download_error_csv,
    get,
    get_base_url,
    post,
    semantic_search,
    upload,
)


def test_get_base_url_default():
    with patch.dict("os.environ", {}, clear=True):
        url = get_base_url()
        assert url == "http://127.0.0.1:8000"


def test_get_base_url_from_env():
    with patch.dict("os.environ", {"API_BASE_URL": "http://api.production.internal/"}):
        url = get_base_url()
        assert url == "http://api.production.internal"


@patch("requests.get")
def test_get_client(mock_get):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"status": "ok"}
    mock_get.return_value = mock_resp

    data = get("/health")
    assert data == {"status": "ok"}
    mock_get.assert_called_once()


@patch("requests.get")
def test_check_health_client(mock_get):
    from dashboard.api_client import check_health

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"status": "ok", "database": "connected", "total_catalog_items": 10}
    mock_get.return_value = mock_resp

    res = check_health(timeout=15)
    assert res["status"] == "ok"
    assert res["database"] == "connected"
    mock_get.assert_called_once_with("http://127.0.0.1:8000/health", timeout=15)



@patch("requests.post")
def test_post_client(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"insights": "good"}
    mock_post.return_value = mock_resp

    data = post("/api/v1/ai/insights", payload={"test": 123}, timeout=25)
    assert data == {"insights": "good"}
    mock_post.assert_called_once_with(
        "http://127.0.0.1:8000/api/v1/ai/insights",
        json={"test": 123},
        timeout=25,
    )


@patch("dashboard.api_client.get")
def test_semantic_search_client(mock_get):
    mock_get.return_value = [{"sku": "SKU-1", "similarity_score": 0.95}]
    res = semantic_search(query="wireless headphones", limit=5)
    assert len(res) == 1
    assert res[0]["sku"] == "SKU-1"
    mock_get.assert_called_once_with(
        "/api/v1/items/search-semantic",
        params={"query": "wireless headphones", "limit": 5},
    )


@patch("dashboard.api_client.post")
def test_ask_copilot_client(mock_post):
    mock_post.return_value = {"response": "Valuation is high", "tool_used": "query_inventory_overview"}
    res = ask_copilot("What is valuation?", history=[{"role": "user", "content": "hi"}])
    assert res["tool_used"] == "query_inventory_overview"
    mock_post.assert_called_once_with(
        "/api/v1/ai/ask",
        payload={"query": "What is valuation?", "history": [{"role": "user", "content": "hi"}]},
        timeout=45,
    )


@patch("requests.get")
def test_download_error_csv_client(mock_get):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = "Row Number,SKU,Error Code\n2,SKU-1,VALIDATION_ERROR"
    mock_get.return_value = mock_resp

    csv_text = download_error_csv(10)
    assert "Row Number,SKU,Error Code" in csv_text
    mock_get.assert_called_once_with(
        "http://127.0.0.1:8000/api/v1/ingestion/jobs/10/export-errors",
        timeout=30,
    )


@patch("dashboard.api_client.post")
def test_diagnose_job_client(mock_post):
    mock_post.return_value = {"health_score": 90, "root_causes": []}
    res = diagnose_job(5)
    assert res["health_score"] == 90
    mock_post.assert_called_once_with("/api/v1/ai/diagnose/5", timeout=45)


@patch("requests.post")
def test_upload_client_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"records_processed": 5}
    mock_post.return_value = mock_resp

    file_obj = io.BytesIO(b"sku,name\nSKU-1,Item 1")
    file_obj.name = "test.csv"

    result = upload("/api/v1/ingest", file_obj)
    assert result == {"records_processed": 5}
    mock_post.assert_called_once()


@patch("requests.post")
def test_upload_client_failure(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"detail": "Bad CSV format"}
    mock_post.return_value = mock_resp

    file_obj = io.BytesIO(b"bad content")
    file_obj.name = "bad.csv"

    with pytest.raises(requests.HTTPError, match="Upload failed"):
        upload("/api/v1/ingest", file_obj)
