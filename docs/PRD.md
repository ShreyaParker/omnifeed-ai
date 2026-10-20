# OmniFeed AI — Product Requirements Document (PRD)

**Version:** 2.1.0  
**Status:** Approved & Production-Ready  
**Date:** October 2026  
**Stack:** Python 3.13 | FastAPI | SQLAlchemy 2.0 | PostgreSQL (Supabase with `pgvector`) | Streamlit | Plotly | Google Gemini AI (`gemini-1.5-flash`, `gemini-embedding-001`) | Pytest  

---

## 1. Executive Summary

OmniFeed AI is an enterprise-grade inventory ingestion, automated data-quality validation, vector semantic search (RAG), and operational copilot platform. It ingests supplier inventory feeds in heterogeneous formats (CSV, JSON, XML), sanitizes dirty and irregular data, enforces strict business rules, executes idempotent database upserts in PostgreSQL, and presents live operational intelligence through an executive-grade Operations Command Center dashboard.

The platform integrates:
1. **Universal Multi-Format Ingestion:** Streaming parsers for CSV (`utf-8-sig`), JSON, and XML (`defusedxml`) with intra-file duplicate rejection and row-level audit logging.
2. **PostgreSQL + `pgvector` Semantic RAG:** 768-dimensional product embeddings (`gemini-embedding-001`) with HNSW cosine distance indexing, intent parsing with SQL price bounds, and semantic similarity thresholds (`min_similarity >= 0.55`).
3. **Conversational OmniBot Copilot:** Real-time AI analyst powered by Google Gemini Function Calling bound to strict read-only SQL database execution tools (`query_inventory_overview`, `search_inventory_items`, `get_critical_stock_alerts`, `get_category_breakdown`), with 100% deterministic database grounding fallbacks.
4. **Automated Supplier Quality Diagnostics & Remediation:** Feed health auditing, root-cause categorization, downloadable error CSV packages (`/export-errors`), and corrective supplier guidelines.
5. **Executive Operations Command Center:** High-density SaaS dashboard featuring top navigation, 4 KPI cards with delta pill badges, dynamic Plotly visual analytics, and an integrated 1-click theme switcher supporting both **Warm Cream Light Mode** (`#FAF8F5`, zero neon) and **Slate Dark Mode** (`#0B0F19`).

---

## 2. Problem Statement

Retailers, wholesalers, and e-commerce aggregators manage supplier catalogs under frequent operational friction:
1. **Format Fragmentation:** Inbound files arrive as CSV with UTF BOMs, nested JSON structures, or deeply nested XML trees.
2. **Data Dirtiness & Inconsistencies:** Embedded currency symbols (`$`, `€`, `INR`, `USD`), comma separators, negative stock values, missing fields, and whitespace irregularities.
3. **Keyword-Only Search Failures:** Traditional SQL keyword searches fail on conceptual queries (e.g., searching for *"ergonomic accessories"* misses mice or chairs unless verbatim matches exist; or searching *"wireless under 100"* returns chairs if prices are ignored).
4. **Hallucination-Prone AI:** Standard LLMs hallucinate stock levels or prices without strict database grounding.
5. **Slow Supplier Dispute Cycles:** Operations teams spend hours manually formatting error reports to email back to suppliers when catalog uploads fail validation.

OmniFeed AI addresses each challenge via an end-to-end atomic pipeline, vector embeddings, Gemini function calling, automated diagnostic remediation, and an executive dashboard.

---

## 3. User Personas

| Persona | Role | Core Need |
| :--- | :--- | :--- |
| **Inventory Operations Director** | Oversees warehouse inventory health, valuations & stockout risks | Real-time visibility into total catalog valuation, stockout alerts, and executive summaries. |
| **Procurement & Supply Chain Lead** | Manages supplier relations and purchase orders | Conversational AI copilot to query stock status, check price boundaries, and detect reorder triggers. |
| **Data Integration Engineer** | Manages supplier data pipelines & ETL gateways | Multi-format support, row-level error reporting, downloadable error CSVs, and automated diagnostic summaries. |

---

## 4. Product Objectives & Current Status

| Objective | Success Criteria | Status |
| :--- | :--- | :--- |
| **Multi-Format Ingestion** | Ingest CSV (`utf-8-sig`), JSON (top-level or `items`), and XML (`defusedxml`). | **Complete** (100% coverage) |
| **Strict Data Quality** | Detect negative stocks, missing required fields, price irregularities, and intra-file duplicate SKUs. | **Complete** |
| **Idempotent Upsert** | Re-uploading existing SKUs updates price, stock, and category without row duplication. | **Complete** (`uq_inventory_sku`) |
| **Vector Semantic Search** | 768-dim embeddings via `pgvector` with HNSW index, query intent parser (`parse_search_intent`), and price boundary filters. | **Complete** (`/search-semantic`) |
| **AI Copilot (Function Calling)** | Grounded conversational analyst using Gemini Function Calling bound to PostgreSQL read-only tools with zero hallucination. | **Complete** (`/api/v1/ai/ask`) |
| **Supplier Diagnostics & CSV Export** | Root-cause error analysis and downloadable supplier remediation CSV. | **Complete** (`/diagnose`, `/export-errors`) |
| **Executive SaaS Dashboard** | 4-tab Streamlit dashboard with KPI tiles, Plotly analytics, top navigation, and 1-click Light/Dark theme switch. | **Complete** (`localhost:8501`) |
| **Automated Test Suite** | Comprehensive unit, integration, and client tests. | **Complete (57/57 passed)** |

---

## 5. Functional Requirements Breakdown

### 5.1 Ingestion & ETL Engine
- **Formats:** `.csv`, `.json`, `.xml` (in-memory parsing via `io.BytesIO`, up to 10 MB per file).
- **Normalization:** Strip whitespace, convert currencies (`$`, `€`, `INR`, `USD`) into `Decimal(10, 2)`, reject negative stocks, validate string lengths.
- **Transaction Safety:** Single atomic transaction boundary per upload (`db.commit()` on success, `db.rollback()` on error).
- **Audit Logging:** Every batch persists job metrics in `ingestion_jobs` and row-level issues in `ingestion_errors`.

### 5.2 Vector Embedding & RAG Pipeline
- **Embedding Model:** `gemini-embedding-001` configured to 768 dimensions via Google GenAI SDK.
- **Storage:** `pgvector` column `embedding Vector(768)` on `inventory_items` with an HNSW cosine distance index.
- **Intent Parsing:** Extracts price thresholds (`"under 100"` -> `max_price = 100.0`), strips filler words (`good`, `best`, `top`, `cheap`), and maps natural concepts.
- **Precision Matching:** Enforces SQL price constraints, cosine distance threshold (`min_similarity >= 0.55`), and name token verification so unrelated products are never matched.

### 5.3 AI Operations Copilot
- **Architecture:** Function-calling agent powered by `gemini-1.5-flash` bound to:
  - `query_inventory_overview(db)`
  - `search_inventory_items(db, query, category, limit)`
  - `get_critical_stock_alerts(db, threshold)`
  - `get_category_breakdown(db)`
- **Grounding & Fallback:** Synthesizes structured data returned by live database queries. If GenAI API quota (Free Tier 5 RPM) is saturated, gracefully falls back to deterministic rule synthesis.

### 5.4 Supplier Diagnostic & Remediation Engine
- **Audit Diagnostics:** Aggregates error patterns (e.g. `MISSING_FIELD`, `INVALID_PRICE`, `DUPLICATE_SKU`) per job.
- **Remediation Guidelines:** Generates step-by-step corrective actions for suppliers.
- **CSV Error Export:** Provides standard RFC 4180 CSV download with row numbers, erroneous values, and correction tips.

### 5.5 Presentation Dashboard (Operations Command Center)
- **Top Navigation & Executive Header:** Unified banner with live DB status badge and 1-click theme switch button. Sidebar completely hidden.
- **Dual Industry-Standard Themes:**
  - **Warm Cream Light:** `#FAF8F5` background, `#FFFFFF` cards, `#2C221A` typography, warm terracotta, cognac, and muted sage accents (zero neon).
  - **Slate Dark:** `#0B0F19` background, `#131B2E` cards, `#F8FAFC` typography, cool emerald, and sky blue accents.
- **4 Tabs:**
  1. `📊 Executive Overview`: 4 KPI cards (Catalog count, ₹ Valuation, Low Stock, Stockouts) + Plotly Bar & Donut charts.
  2. `⚡ Ingestion & ETL Studio`: Drag-and-drop feed uploader + live metrics + audit log table + diagnostic trigger.
  3. `🔍 Intelligent Catalog`: Semantic AI search (RAG) vs exact search + category filters + stock filters.
  4. `💬 OmniBot Copilot`: Interactive chat interface + quick action pills + verified live SQL citations.

---

## 6. Non-Functional Requirements

- **Security:** Parameterized SQL queries via SQLAlchemy ORM; XML entity expansion protection via `defusedxml`; bounded upload sizes (≤ 10MB).
- **Resilience:** Graceful fallbacks across all AI components when API keys are absent or rate-limited.
- **Performance:** Sub-second response times on vector lookups using HNSW index; < 1.5s batch ingestion for standard catalogs.
- **Test Integrity:** 57 automated pytest tests passing across parsers, RAG queries, tools, API routes, and dashboard client.
