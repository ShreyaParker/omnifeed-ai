"""
OmniFeed AI - Export-House Catalog Demonstration Data Seeder
Standalone utility script to initialize database tables, ingest the Accessories Catalog,
and generate vector embeddings for semantic search & RAG Copilot operations.
"""

from decimal import Decimal
import os
from pathlib import Path
import sys
import time

# Ensure project root is on sys.path for standalone script execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select
from app.database import Category, IngestionJob, InventoryItem, SessionLocal, init_db
from app.parsers import CSVParser
from app.services.embedding_service import batch_embed_items
from app.services.ingestion import ingest_records


def seed_demo_data(catalog_filename: str = "accessories_catalog.csv") -> dict:
    """
    Initializes database schema, parses the specified catalog CSV,
    executes atomic ingestion, and ensures vector embeddings are generated.
    """
    start_time = time.perf_counter()

    print("\n" + "=" * 70)
    print("        OmniFeed AI - Live Demo Data Seeding Utility")
    print("=" * 70)

    # 1. Initialize DB tables and pgvector extension if PostgreSQL
    print("[1/4] Initializing database schema and vector extensions...")
    init_db()

    # 2. Locate and parse sample dataset
    catalog_path = PROJECT_ROOT / "sample_data" / catalog_filename
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog file not found: {catalog_path}")

    print(f"[2/4] Parsing catalog feed: {catalog_path.relative_to(PROJECT_ROOT)}...")
    file_bytes = catalog_path.read_bytes()
    parser = CSVParser()
    records = list(parser.parse(file_bytes))

    # 3. Ingest records with upsert and duplicate detection
    print(f"[3/4] Ingesting {len(records)} records into inventory tables...")
    with SessionLocal() as db:
        summary = ingest_records(
            db=db,
            records=records,
            filename=catalog_path.name,
            file_type="csv",
        )

        # 4. Auto-generate any pending vector embeddings
        print("[4/4] Verifying and generating vector embeddings...")
        newly_embedded = batch_embed_items(db)

        # Gather final counts
        total_items = db.scalar(select(func.count(InventoryItem.id))) or 0
        total_cats = db.scalar(select(func.count(Category.id))) or 0
        total_embedded = db.scalar(
            select(func.count(InventoryItem.id)).where(InventoryItem.embedding.isnot(None))
        ) or 0

    elapsed_time = time.perf_counter() - start_time

    # Output formatted confirmation summary
    print("-" * 70)
    print("FEED SEEDING CONFIRMATION SUMMARY")
    print("-" * 70)
    print(f"Catalog File:         {catalog_path.name}")
    print(f"Ingestion Status:     {summary.get('status', 'unknown').upper()}")
    print(f"Execution Time:       {elapsed_time:.3f} seconds")
    print(f"Records Processed:    {summary.get('records_processed', 0)}")
    print(f"Records Inserted:     {summary.get('records_inserted', 0)}")
    print(f"Records Updated:      {summary.get('records_updated', 0)}")
    print(f"Records Failed:       {summary.get('records_failed', 0)}")
    print(f"Total Database Items: {total_items}")
    print(f"Total Categories:     {total_cats}")
    print(f"Embedded Items:       {total_embedded}/{total_items} (Batch Added: {newly_embedded})")
    print("=" * 70 + "\n")

    return {
        "status": summary.get("status"),
        "records_processed": summary.get("records_processed", 0),
        "records_inserted": summary.get("records_inserted", 0),
        "records_updated": summary.get("records_updated", 0),
        "records_failed": summary.get("records_failed", 0),
        "total_items": total_items,
        "total_categories": total_cats,
        "total_embedded": total_embedded,
        "execution_time_seconds": elapsed_time,
    }


if __name__ == "__main__":
    try:
        seed_demo_data()
    except Exception as exc:
        print(f"\n[ERROR] Seeding failed: {exc}", file=sys.stderr)
        sys.exit(1)
