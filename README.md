# ⚡ OmniFeed AI — Operations Command Center

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791.svg)](https://supabase.com/)
[![pgvector](https://img.shields.io/badge/pgvector-0.3.6+-336791.svg)](https://github.com/pgvector/pgvector)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.40+-FF4B4B.svg)](https://streamlit.io/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-1.5%20Flash-4285F4.svg)](https://ai.google.dev/)
[![Tests](https://img.shields.io/badge/tests-57%20passed-brightgreen.svg)](tests/)

OmniFeed AI is an enterprise-grade inventory ingestion, automated validation, semantic vector retrieval (RAG), and conversational copilot platform. It normalizes dirty supplier feeds (CSV, JSON, XML), enforces strict business rules, performs idempotent database upserts into PostgreSQL, indexes products with 768-dimensional dense vector embeddings (`pgvector`), and powers an executive-grade Operations Command Center dashboard.

---

## 🌟 Key Features

### 1. ⚡ Universal Multi-Format Ingestion
- **Streaming Parsers:** Native support for `.csv` (`utf-8-sig` with BOM handling), `.json` (array or root `items` dict), and `.xml` (hardened with `defusedxml`).
- **Data Normalization:** Trims whitespace, sanitizes multi-currency notations (`$`, `€`, `INR`, `USD`) into `Decimal(10, 2)`, rejects negative stocks, and detects intra-file duplicate SKUs.
- **Transactional Safety:** Atomic single-transaction boundary per upload (`db.commit()` on success, `db.rollback()` on error) with row-level error audit logs.

### 2. 🔍 Precision Hybrid Vector Search (RAG)
- **Dense Vector Embeddings:** 768-dimensional embeddings generated via `gemini-embedding-001` and indexed using PostgreSQL `pgvector` with an **HNSW cosine distance index** (`m=16, ef_construction=64`).
- **Query Intent Parsing:** Extracts SQL price boundaries (e.g., `"under 100"` -> `unit_price <= 100.0`), removes conversational filler noise (`good`, `best`, `cheap`), and maps core product concepts.
- **Precision Matching:** Combines cosine distance thresholds (`min_similarity >= 0.55`), strict price limits, and title token verification so irrelevant items never match (e.g., chairs matching mouse queries).

### 3. 💬 OmniBot Operations Copilot (Gemini Function Calling)
- **Grounded Conversational Analyst:** Powered by `gemini-1.5-flash` bound to strict read-only PostgreSQL execution tools:
  - `query_inventory_overview(db)`
  - `search_inventory_items(db, query, category, limit)`
  - `get_critical_stock_alerts(db, threshold)`
  - `get_category_breakdown(db)`
- **Zero Hallucination Fallback:** When Google GenAI API rate limits are hit, the copilot automatically executes the tools deterministically and synthesizes real database answers.

### 4. 🔬 Supplier Quality Diagnostics & Remediation
- **Root Cause Analysis:** Groups feed failures by code (`INVALID_PRICE`, `NEGATIVE_STOCK`, `DUPLICATE_SKU`, `MISSING_FIELD`).
- **Remediation Packages:** Generates step-by-step corrective guidelines for suppliers.
- **CSV Error Export:** Downloadable RFC 4180 CSV export (`/api/v1/ingestion/jobs/{id}/export-errors`) containing exact row numbers and error messages for supplier communication.

### 5. 🎨 Executive SaaS Operations Dashboard
- **Top Navigation Bar:** Full-width executive header with live database connectivity status badge (`🟢 Live DB Connected`) and an integrated 1-click theme switch button (`🌙 Dark Mode` / `☀️ Cream Mode`). The clumsy sidebar has been completely eliminated.
- **Dual Industry-Standard Themes:**
  - **Warm Cream Light Mode:** `#FAF8F5` background, `#FFFFFF` cards, `#2C221A` typography, warm terracotta and sage accents (strictly zero neon).
  - **Slate Dark Mode:** `#0B0F19` background, `#131B2E` cards, `#F8FAFC` typography, emerald and sky blue accents.
- **4 Dedicated Studio Tabs:**
  1. `📊 Executive Overview`: 4 KPI metric cards (Total SKUs, ₹ Valuation, Low Stock, Stockouts) with delta pill badges + Plotly valuation bar & category donut charts.
  2. `⚡ Ingestion & ETL Studio`: Drag-and-drop supplier uploader, live row metrics, audit log table, and diagnostic trigger.
  3. `🔍 Intelligent Catalog`: Semantic AI search (RAG) vs exact search + category filters + stock availability filters.
  4. `💬 OmniBot Copilot`: Interactive chat interface with quick action prompt pills and verified live SQL database citations.

---

## 🏗️ System Architecture

```mermaid
graph TD
    User([Operations / Procurement User]) -->|Browser| Dashboard[Streamlit Dashboard :8501]
    Dashboard -->|REST API /api/v1| Router[FastAPI Router :8000]
    
    subgraph FastAPI Application
        Router --> IngestService[Ingestion Service]
        Router --> CopilotService[Copilot & RAG Service]
        Router --> DiagService[Diagnostic Service]
        IngestService --> EmbedService[Embedding Service]
    end

    subgraph Storage & Vector Engine [PostgreSQL / Supabase]
        IngestService -->|Atomic Upsert| DB[(PostgreSQL)]
        EmbedService -->|Vector Writes| DB
        CopilotService -->|HNSW Cosine Vector Search| DB
        CopilotService -->|Strict Read-Only SQL Tools| DB
    end

    subgraph AI Intelligence
        EmbedService -->|gemini-embedding-001| GoogleEmbed[Google GenAI Embeddings]
        CopilotService -->|gemini-1.5-flash Function Calling| Gemini[Google Gemini Flash API]
    end
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.13+ installed
- PostgreSQL with `pgvector` extension enabled (Supabase recommended)
- Google Gemini API key (optional for LLM; deterministic rules fallback is active if missing)

### 2. Environment Configuration
Clone the repository and copy the environment template:
```bash
cp .env.example .env
```
Ensure `.env` contains your database and Gemini credentials:
```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-1.5-flash
EMBEDDING_MODEL=gemini-embedding-001
API_BASE_URL=http://127.0.0.1:8000
```

### 3. Installation
Create a virtual environment and install dependencies:
```bash
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate # macOS/Linux

pip install -r requirements.txt
```

### 4. Launch Backend API
Start the FastAPI server on port 8000:
```bash
uvicorn app.main:app --reload --port 8000
```
Interactive API docs are available at `http://127.0.0.1:8000/docs`.

### 5. Launch Operations Dashboard
In a separate terminal, start the Streamlit command center:
```bash
streamlit run dashboard/streamlit_app.py
```
Open `http://localhost:8501` in your browser.

---

## 📡 REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Health check & PostgreSQL connectivity verification |
| `POST` | `/api/v1/ingest` | Upload supplier catalog (`.csv`, `.json`, `.xml`) with atomic upserts |
| `GET` | `/api/v1/items` | Paginated catalog list with search, category & price filters |
| `GET` | `/api/v1/items/{sku}` | Lookup a single product record by SKU |
| `GET` | `/api/v1/items/search-semantic` | Hybrid vector semantic search with query intent parsing |
| `GET` | `/api/v1/analytics/overview` | Total SKUs, valuation in ₹, low-stock, and out-of-stock counts |
| `GET` | `/api/v1/analytics/categories` | Grouped valuation and unit counts by category |
| `GET` | `/api/v1/analytics/stock-alerts` | Products with inventory below safety threshold (< 10) |
| `GET` | `/api/v1/ingestion/history` | Historical audit log of all batch upload jobs |
| `POST` | `/api/v1/ingestion/jobs/{id}/diagnose` | Root-cause error analysis and remediation guidelines |
| `GET` | `/api/v1/ingestion/jobs/{id}/export-errors` | Stream RFC 4180 CSV with row-level validation errors |
| `POST` | `/api/v1/ai/insights` | Operations executive summary generated by Gemini |
| `POST` | `/api/v1/ai/ask` | Conversational copilot query via Gemini Function Calling |

---

## 🧪 Testing

Run the automated test suite with pytest:
```bash
pytest -v
```

**Test Coverage Summary (57 passed in 31.8s):**
- `tests/test_parsers.py`: CSV BOM, JSON array/items, XML defusedxml parsing, and edge cases.
- `tests/test_ingestion.py`: Price parsing, currency stripping, intra-file duplicate SKU rejection, upsert logic.
- `tests/test_api.py`: Core REST endpoints, health check, pagination, filtering.
- `tests/test_api_v2.py`: RAG search endpoint, copilot ask endpoint, CSV error export.
- `tests/test_copilot_and_diagnostic.py`: Gemini Function Calling, tool calling functions, deterministic fallbacks, supplier diagnostics.
- `tests/test_embedding_service.py`: Vector generation, batch embedding, and ingestion pipeline integration.
- `tests/test_rag.py`: Semantic similarity search query construction and precision filtering.
- `tests/test_dashboard_client.py`: API client methods, timeouts, and error handling.

---

## 📚 Documentation Index

For in-depth architectural specifications and implementation details, refer to:
- 📄 [PRD.md](docs/PRD.md) — Product requirements, user personas, and acceptance criteria.
- 🏛️ [ARCHITECTURE.md](docs/ARCHITECTURE.md) — Three-tier architecture, sequence diagrams, and module responsibilities.
- 🎨 [DESIGN.md](docs/DESIGN.md) — Database schema, pgvector HNSW index, UI design tokens, and error recovery policies.
- 🗺️ [ROADMAP.md](docs/ROADMAP.md) — Development timeline, completed milestones, and upcoming features.
