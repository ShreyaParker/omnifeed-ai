import os
from typing import Any
import requests
import streamlit as st


def get_base_url() -> str:
    """Retrieve API base URL from st.secrets, environment variables, or default."""
    try:
        if hasattr(st, "secrets") and "API_BASE_URL" in st.secrets:
            return str(st.secrets["API_BASE_URL"]).rstrip("/")
    except Exception:
        pass
    return os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def check_health(timeout: int = 15) -> dict[str, Any]:
    """
    Active wake-up check pinging GET /health with a configurable (default 15s) timeout.
    Raises requests.RequestException if the backend is cold-starting or unreachable.
    """
    base_url = get_base_url()
    url = f"{base_url}/health"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get(path: str, params: dict[str, Any] | None = None) -> Any:
    """
    Send GET request to OmniFeed backend API.
    Raises requests.RequestException on connection or HTTP errors.
    """
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=30)
def get_cached_analytics_overview() -> dict[str, Any]:
    """Cached high-level inventory valuation and health overview (TTL: 30s)."""
    return get("/api/v1/analytics/overview")


@st.cache_data(ttl=30)
def get_cached_analytics_categories() -> list[dict[str, Any]]:
    """Cached category-level stock and valuation breakdown (TTL: 30s)."""
    return get("/api/v1/analytics/categories")


@st.cache_data(ttl=30)
def get_cached_stock_alerts(threshold: int = 10) -> list[dict[str, Any]]:
    """Cached stock alerts for inventory health monitoring (TTL: 30s)."""
    return get("/api/v1/analytics/stock-alerts", params={"threshold": threshold})


@st.cache_data(ttl=30)
def get_cached_ingestion_history() -> dict[str, Any]:
    """Cached audit history of recent ingestion jobs (TTL: 30s)."""
    return get("/api/v1/ingestion/history")


def post(
    path: str,
    payload: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    """
    Send POST request to OmniFeed backend API with configurable timeout.
    Accepts payload or json_data for backward compatibility.
    Raises requests.RequestException on connection or HTTP errors.
    """
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"
    body = payload if payload is not None else json_data
    response = requests.post(url, json=body, timeout=timeout)
    response.raise_for_status()
    return response.json()


def upload(path: str, file: Any) -> dict[str, Any]:
    """
    Upload a file to the OmniFeed backend API.
    Handles Streamlit UploadedFile, file-like objects, or bytes.
    Raises requests.HTTPError or requests.RequestException on failure.
    """
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    filename = getattr(file, "name", "uploaded_file.dat")
    if hasattr(file, "getvalue"):
        content = file.getvalue()
    elif hasattr(file, "read"):
        content = file.read()
    else:
        content = bytes(file)

    files = {"file": (filename, content, "application/octet-stream")}
    response = requests.post(url, files=files, timeout=60)

    if not response.ok:
        try:
            err_data = response.json()
            detail = err_data.get("detail", response.text)
        except Exception:
            detail = response.text
        raise requests.HTTPError(f"Upload failed ({response.status_code}): {detail}", response=response)

    return response.json()


def semantic_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Execute semantic AI vector search (RAG) against catalog."""
    return get("/api/v1/items/search-semantic", params={"query": query, "limit": limit})


def ask_copilot(query: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Interact with OmniBot Copilot using Gemini Function Calling."""
    return post("/api/v1/ai/ask", payload={"query": query, "history": history or []}, timeout=45)


def download_error_csv(job_id: int) -> str:
    """Download row-level ingestion errors as raw CSV text."""
    base_url = get_base_url()
    url = f"{base_url}/api/v1/ingestion/jobs/{job_id}/export-errors"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def diagnose_job(job_id: int) -> dict[str, Any]:
    """Generate supplier feed diagnostics and root cause remediation."""
    return post(f"/api/v1/ai/diagnose/{job_id}", timeout=45)
