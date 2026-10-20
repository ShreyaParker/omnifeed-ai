import csv
from datetime import datetime, timezone
import io
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import (
    Category,
    IngestionError,
    IngestionJob,
    InventoryItem,
    get_db,
    init_db,
)
from app.parsers import CSVParser, JSONParser, XMLParser
from app.services.ai_service import generate_insights
from app.services.copilot_service import ask_inventory_copilot, search_inventory_items
from app.services.diagnostic_service import generate_supplier_diagnostic
from app.services.embedding_service import generate_embedding
from app.services.ingestion import ingest_records

PARSERS = {
    ".csv": CSVParser(),
    ".json": JSONParser(),
    ".xml": XMLParser(),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as exc:
        import logging
        logging.getLogger("uvicorn.error").error("Database initialization error during startup: %s", exc)
    yield


app = FastAPI(
    title="OmniFeed AI",
    version="2.1.0",
    description="Intelligent Inventory Ingestion, Validation & Analytics API",
    lifespan=lifespan,
)

settings = get_settings()
raw_origins = getattr(settings, "allowed_origins", "*") or "*"
if raw_origins.strip() == "*":
    cors_origins = ["*"]
else:
    cors_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["System"])
def root():
    """Lightweight operational probe for cloud load balancers and container orchestrators."""
    return {
        "app": "OmniFeed AI",
        "status": "operational",
        "version": "2.1.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    """Health check endpoint returning database connectivity status, catalog item count, and timestamp."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(select(1))
        total_items = db.scalar(select(func.count(InventoryItem.id))) or 0
        return {
            "status": "ok",
            "database": "connected",
            "total_catalog_items": total_items,
            "total_items": total_items,
            "timestamp": now_iso,
        }
    except Exception as exc:
        return Response(
            content=json.dumps({
                "status": "degraded",
                "database": "disconnected",
                "total_catalog_items": 0,
                "total_items": 0,
                "timestamp": now_iso,
                "error": str(exc),
            }),
            status_code=503,
            media_type="application/json",
        )


@app.post("/api/v1/ingest", tags=["ETL Ingestion"])
async def ingest_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload and ingest inventory files in CSV, JSON, or XML format.
    Enforces file size limits, parses content in memory, and atomically upserts records.
    """
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    parser = PARSERS.get(suffix)

    if parser is None:
        raise HTTPException(
            status_code=400,
            detail="Supported file formats are CSV, JSON, and XML.",
        )

    current_settings = get_settings()
    max_bytes = current_settings.max_upload_mb * 1024 * 1024

    # Check file.size attribute upfront to reject before allocating memory buffers
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {current_settings.max_upload_mb} MB.",
        )

    # Read content in progressive chunks to prevent memory spikes on small cloud containers
    buffer = bytearray()
    chunk_size = 1024 * 1024  # 1 MB chunks
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds maximum allowed size of {current_settings.max_upload_mb} MB.",
            )

    content = bytes(buffer)
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        records = parser.parse(content)
        summary = ingest_records(
            db=db,
            records=records,
            filename=filename,
            file_type=suffix.lstrip("."),
        )
        return summary
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Ingestion failed due to a server or database error.",
        ) from exc


@app.get("/api/v1/items", tags=["Catalog"])
def list_items(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    category: str | None = Query(None, description="Filter by category name"),
    search: str | None = Query(None, description="Search across SKU or item name"),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum unit price"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum unit price"),
    db: Session = Depends(get_db),
):
    """Retrieve paginated inventory items with filtering and search."""
    if min_price is not None and max_price is not None:
        if min_price > max_price:
            raise HTTPException(
                status_code=400,
                detail="min_price cannot exceed max_price.",
            )

    stmt = (
        select(InventoryItem, Category.name.label("category_name"))
        .outerjoin(Category, InventoryItem.category_id == Category.id)
    )

    if category:
        stmt = stmt.where(Category.name == category)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            InventoryItem.name.ilike(pattern) | InventoryItem.sku.ilike(pattern)
        )
    if min_price is not None:
        stmt = stmt.where(InventoryItem.unit_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(InventoryItem.unit_price <= max_price)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(InventoryItem.sku)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    items = [
        {
            "id": row.InventoryItem.id,
            "sku": row.InventoryItem.sku,
            "name": row.InventoryItem.name,
            "category": row.category_name or "Uncategorized",
            "stock_quantity": row.InventoryItem.stock_quantity,
            "unit_price": str(row.InventoryItem.unit_price),
            "created_at": (
                row.InventoryItem.created_at.isoformat()
                if row.InventoryItem.created_at
                else None
            ),
            "updated_at": (
                row.InventoryItem.updated_at.isoformat()
                if row.InventoryItem.updated_at
                else None
            ),
        }
        for row in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
    }


@app.get("/api/v1/items/search-semantic", tags=["Catalog"])
def search_semantic(
    query: str = Query(..., min_length=1, description="Semantic text query to search for similar products"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of items to return"),
    db: Session = Depends(get_db),
):
    """
    Perform semantic vector and hybrid search using cosine similarity on InventoryItem.embedding.
    Parses search intent (price limits, keywords) and falls back gracefully to text pattern matching.
    """
    return search_inventory_items(db, query=query, limit=limit)


@app.get("/api/v1/items/{sku}", tags=["Catalog"])
def get_item(sku: str, db: Session = Depends(get_db)):
    """Retrieve details for a single product by SKU."""
    row = db.execute(
        select(InventoryItem, Category.name.label("category_name"))
        .outerjoin(Category, InventoryItem.category_id == Category.id)
        .where(InventoryItem.sku == sku)
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Item with SKU '{sku}' not found.")

    item = row.InventoryItem
    return {
        "id": item.id,
        "sku": item.sku,
        "name": item.name,
        "category": row.category_name or "Uncategorized",
        "stock_quantity": item.stock_quantity,
        "unit_price": str(item.unit_price),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _get_overview_data(db: Session) -> dict[str, Any]:
    """Calculate aggregated inventory overview metrics."""
    stats = db.execute(
        select(
            func.count(InventoryItem.id).label("total_skus"),
            func.coalesce(func.sum(InventoryItem.stock_quantity), 0).label("total_units"),
            func.coalesce(
                func.sum(InventoryItem.stock_quantity * InventoryItem.unit_price), 0
            ).label("inventory_valuation"),
        )
    ).first()

    total_skus = stats.total_skus if stats else 0
    total_units = int(stats.total_units if stats else 0)
    inventory_val = Decimal(str(stats.inventory_valuation if stats else 0)).quantize(
        Decimal("0.01")
    )

    low_stock = (
        db.scalar(
            select(func.count(InventoryItem.id)).where(InventoryItem.stock_quantity < 10)
        )
        or 0
    )

    out_of_stock = (
        db.scalar(
            select(func.count(InventoryItem.id)).where(InventoryItem.stock_quantity == 0)
        )
        or 0
    )

    return {
        "total_skus": total_skus,
        "total_units": total_units,
        "inventory_valuation": str(inventory_val),
        "low_stock_items": low_stock,
        "out_of_stock_items": out_of_stock,
    }


@app.get("/api/v1/analytics/overview", tags=["Analytics"])
def analytics_overview(db: Session = Depends(get_db)):
    """Return high-level inventory valuation and health metrics."""
    return _get_overview_data(db)


@app.get("/api/v1/analytics/categories", tags=["Analytics"])
def analytics_categories(db: Session = Depends(get_db)):
    """Return inventory valuation and item counts grouped by category."""
    stmt = (
        select(
            func.coalesce(Category.name, "Uncategorized").label("category"),
            func.count(InventoryItem.id).label("sku_count"),
            func.coalesce(func.sum(InventoryItem.stock_quantity), 0).label("total_units"),
            func.coalesce(
                func.sum(InventoryItem.stock_quantity * InventoryItem.unit_price), 0
            ).label("total_valuation"),
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
            "total_units": int(row.total_units),
            "total_valuation": str(
                Decimal(str(row.total_valuation)).quantize(Decimal("0.01"))
            ),
        }
        for row in rows
    ]


def _get_stock_alerts_data(db: Session, threshold: int = 10) -> list[dict[str, Any]]:
    """Query items below stock threshold."""
    stmt = (
        select(InventoryItem, Category.name.label("category_name"))
        .outerjoin(Category, InventoryItem.category_id == Category.id)
        .where(InventoryItem.stock_quantity < threshold)
        .order_by(InventoryItem.stock_quantity.asc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "sku": row.InventoryItem.sku,
            "name": row.InventoryItem.name,
            "category": row.category_name or "Uncategorized",
            "stock_quantity": row.InventoryItem.stock_quantity,
            "unit_price": str(row.InventoryItem.unit_price),
        }
        for row in rows
    ]


@app.get("/api/v1/analytics/stock-alerts", tags=["Analytics"])
def stock_alerts(
    threshold: int = Query(10, ge=0, description="Stock threshold for low-stock warning"),
    db: Session = Depends(get_db),
):
    """Return products with stock quantity below the specified threshold."""
    return _get_stock_alerts_data(db, threshold=threshold)


@app.get("/api/v1/ingestion/history", tags=["ETL Ingestion"])
def ingestion_history(db: Session = Depends(get_db)):
    """Return audit history of recent ingestion jobs."""
    jobs = list(
        db.scalars(
            select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(20)
        ).all()
    )
    return {
        "history": [
            {
                "id": j.id,
                "filename": j.filename,
                "file_type": j.file_type,
                "status": j.status,
                "records_processed": j.records_processed,
                "records_inserted": j.records_inserted,
                "records_updated": j.records_updated,
                "records_failed": j.records_failed,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
        "note": "Live ingestion history retrieved from audit log.",
    }


@app.post("/api/v1/ai/insights", tags=["AI Operations"])
def ai_insights(db: Session = Depends(get_db)):
    """Generate executive inventory operations insights using Gemini AI with rule-based fallback."""
    overview = _get_overview_data(db)
    alerts = _get_stock_alerts_data(db, threshold=10)
    return generate_insights(overview, alerts)


class CopilotQueryRequest(BaseModel):
    query: str
    history: list[dict[str, Any]] = Field(default_factory=list)


@app.post("/api/v1/ai/ask", tags=["AI Operations"])
def ask_copilot(
    payload: CopilotQueryRequest,
    db: Session = Depends(get_db),
):
    """
    Enterprise-grade AI Copilot using Gemini Function Calling and live database querying.
    Executes live read-only tools and synthesizes grounded business responses.
    """
    clean_query = payload.query.strip()
    if not clean_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    return ask_inventory_copilot(db=db, user_query=clean_query, chat_history=payload.history)


@app.post("/api/v1/ai/diagnose/{job_id}", tags=["AI Operations"])
def diagnose_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    Generate an AI supplier data diagnostic analyzing root causes,
    a health score (0-100), and actionable vendor instructions for a feed.
    """
    return generate_supplier_diagnostic(db=db, job_id=job_id)


@app.get("/api/v1/ingestion/jobs/{job_id}/export-errors", tags=["ETL Ingestion"])
def export_job_errors(
    job_id: int,
    db: Session = Depends(get_db),
):
    """Generate a downloadable CSV of row-level errors for suppliers."""
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job with ID {job_id} not found.")

    errors = list(
        db.scalars(
            select(IngestionError)
            .where(IngestionError.job_id == job_id)
            .order_by(IngestionError.row_number.asc().nulls_last())
        ).all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Row Number", "SKU", "Error Code", "Error Message", "Raw Record"])

    for err in errors:
        writer.writerow([
            err.row_number if err.row_number is not None else "",
            err.sku or "",
            err.error_code or "",
            err.error_message or "",
            err.raw_record or "",
        ])

    csv_data = output.getvalue()
    filename = f"ingestion_job_{job_id}_errors.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

