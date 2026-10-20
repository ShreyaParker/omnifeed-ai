import re
from decimal import Decimal, InvalidOperation
from typing import Any
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Category, IngestionError, IngestionJob, InventoryItem
from app.services.embedding_service import generate_embedding, generate_item_text


def clean_string(val: Any) -> str:
    """Strip leading/trailing whitespace from value or return empty string."""
    if val is None:
        return ""
    return str(val).strip()


def parse_price(val: Any) -> Decimal:
    """Normalize currency strings (e.g. '$12.50' or '12.50 INR') to Decimal with 2 places."""
    text = clean_string(val)
    if not text:
        raise ValueError("Invalid unit_price.")

    # Remove commas and currency labels/symbols, retain digits, decimal point, and minus sign
    text = text.replace(",", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        raise ValueError("Invalid unit_price.")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Invalid unit_price.") from exc

    if not amount.is_finite() or amount <= 0:
        raise ValueError("unit_price must be greater than zero.")

    # Validate that it doesn't exceed 2 decimal places (ignoring trailing zeros)
    if amount.as_tuple().exponent < -2 and amount.normalize().as_tuple().exponent < -2:
        raise ValueError("unit_price supports at most 2 decimal places.")

    if amount >= Decimal("100000000"):
        raise ValueError("unit_price exceeds the supported maximum.")

    return amount.quantize(Decimal("0.01"))


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a single record dictionary."""
    if not isinstance(row, dict):
        raise ValueError("Record must be a dictionary.")

    if "_parse_error" in row:
        raise ValueError(row["_parse_error"])

    # Normalize keys to lowercase stripped strings
    normalized = {
        clean_string(k).lower(): clean_string(v) if isinstance(v, str) else v
        for k, v in row.items()
    }

    sku = clean_string(normalized.get("sku"))
    name = clean_string(normalized.get("name"))
    category = clean_string(normalized.get("category"))

    if not sku:
        raise ValueError("sku is required.")
    if len(sku) > 64:
        raise ValueError("sku must not exceed 64 characters.")

    if not name:
        raise ValueError("name is required.")
    if len(name) > 255:
        raise ValueError("name must not exceed 255 characters.")

    if not category:
        raise ValueError("category is required.")
    if len(category) > 50:
        raise ValueError("category must not exceed 50 characters.")

    raw_stock = normalized.get("stock_quantity")
    if raw_stock is None or clean_string(raw_stock) == "":
        raise ValueError("stock_quantity is required.")

    try:
        if isinstance(raw_stock, str):
            stock_str = clean_string(raw_stock)
            if "." in stock_str:
                f_val = float(stock_str)
                if not f_val.is_integer():
                    raise ValueError("stock_quantity must be an integer.")
                quantity = int(f_val)
            else:
                quantity = int(stock_str)
        elif isinstance(raw_stock, float):
            if not raw_stock.is_integer():
                raise ValueError("stock_quantity must be an integer.")
            quantity = int(raw_stock)
        else:
            quantity = int(raw_stock)
    except (ValueError, TypeError) as exc:
        raise ValueError("stock_quantity must be an integer.") from exc

    if quantity < 0:
        raise ValueError("stock_quantity cannot be negative.")

    unit_price = parse_price(normalized.get("unit_price"))

    return {
        "sku": sku,
        "name": name,
        "category": category,
        "stock_quantity": quantity,
        "unit_price": unit_price,
    }


def ingest_records(
    db: Session,
    records: Iterable[dict[str, Any]],
    filename: str,
    file_type: str,
) -> dict[str, Any]:
    """
    Ingest parsed records in a single atomic transaction.
    Performs per-row validation, duplicate SKU detection within the file,
    auto-category creation, and idempotent upserts on inventory items.
    """
    processed = 0
    inserted = 0
    updated = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    seen_skus: set[str] = set()
    category_cache: dict[str, Category] = {}

    try:
        for row_number, row in enumerate(records, start=2):
            processed += 1

            try:
                item = normalize_record(row)

                # Check duplicate SKU in the same upload file
                if item["sku"] in seen_skus:
                    raise ValueError(f"Duplicate SKU '{item['sku']}' within the uploaded file.")
                seen_skus.add(item["sku"])

                # Auto-create category if it does not exist
                category = category_cache.get(item["category"])
                if category is None:
                    category = db.scalar(
                        select(Category).where(Category.name == item["category"])
                    )
                    if category is None:
                        category = Category(name=item["category"])
                        db.add(category)
                        db.flush()
                    category_cache[item["category"]] = category

                # Upsert inventory item by SKU
                existing = db.scalar(
                    select(InventoryItem).where(InventoryItem.sku == item["sku"])
                )

                item_text = generate_item_text(
                    name=item["name"],
                    category=item["category"],
                    sku=item["sku"],
                )
                embedding = generate_embedding(item_text)

                if existing is None:
                    new_item = InventoryItem(
                        sku=item["sku"],
                        name=item["name"],
                        category_id=category.id,
                        stock_quantity=item["stock_quantity"],
                        unit_price=item["unit_price"],
                        embedding=embedding,
                    )
                    db.add(new_item)
                    inserted += 1
                else:
                    existing.name = item["name"]
                    existing.category_id = category.id
                    existing.stock_quantity = item["stock_quantity"]
                    existing.unit_price = item["unit_price"]
                    if embedding is not None or existing.embedding is None:
                        existing.embedding = embedding
                    updated += 1

            except ValueError as exc:
                failed += 1
                raw_sku = ""
                if isinstance(row, dict):
                    raw_sku = clean_string(row.get("sku", row.get("SKU", "")))
                errors.append({
                    "row_number": row_number,
                    "sku": raw_sku[:64],
                    "error_code": "VALIDATION_ERROR",
                    "error_message": str(exc),
                })

        # Save IngestionJob and IngestionError audit records
        status = "completed_with_errors" if failed > 0 else "completed"
        job = IngestionJob(
            filename=filename,
            file_type=file_type,
            status=status,
            records_processed=processed,
            records_inserted=inserted,
            records_updated=updated,
            records_failed=failed,
        )
        db.add(job)
        db.flush()

        for err in errors:
            db_err = IngestionError(
                job_id=job.id,
                row_number=err.get("row_number"),
                sku=err.get("sku"),
                error_code=err.get("error_code", "VALIDATION_ERROR"),
                error_message=err.get("error_message", ""),
            )
            db.add(db_err)

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "status": "completed_with_errors" if failed > 0 else "completed",
        "filename": filename,
        "file_type": file_type,
        "records_processed": processed,
        "records_inserted": inserted,
        "records_updated": updated,
        "records_failed": failed,
        "errors": errors,
    }
