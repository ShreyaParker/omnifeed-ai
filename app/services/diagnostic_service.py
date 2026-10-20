import json
import logging
from typing import Any

from fastapi import HTTPException
from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import IngestionError, IngestionJob

logger = logging.getLogger(__name__)


def _rule_based_diagnostic(
    job: IngestionJob,
    errors: list[IngestionError],
    error_breakdown: dict[str, int],
    sample_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic rule-based supplier feed diagnostic when Gemini is unconfigured or unavailable."""
    total = job.records_processed
    failed = job.records_failed
    valid = job.records_inserted + job.records_updated

    if total > 0:
        health_score = max(0, min(100, int(round((valid / total) * 100))))
    else:
        health_score = 100 if failed == 0 else 0

    if failed == 0:
        return {
            "job_id": job.id,
            "filename": job.filename,
            "file_type": job.file_type,
            "status": job.status,
            "records_processed": total,
            "records_inserted": job.records_inserted,
            "records_updated": job.records_updated,
            "records_failed": failed,
            "health_score": 100,
            "summary": (
                f"Supplier feed '{job.filename}' processed cleanly with 100% compliance across {total} records. "
                "No validation errors or formatting anomalies detected."
            ),
            "root_causes": [],
            "actionable_vendor_instructions": [
                "Catalog data meets all schema, type, and constraint specifications. Maintain current feed generation workflow."
            ],
            "error_breakdown": error_breakdown,
            "sample_errors": [],
        }

    # Analyze error messages to extract root causes and vendor remediation
    root_causes: list[str] = []
    instructions: list[str] = []

    has_duplicate = any("duplicate" in (e.error_message or "").lower() for e in errors)
    has_price_err = any("unit_price" in (e.error_message or "").lower() for e in errors)
    has_stock_err = any("stock_quantity" in (e.error_message or "").lower() for e in errors)
    has_required_err = any("required" in (e.error_message or "").lower() for e in errors)

    if has_duplicate:
        root_causes.append("Duplicate SKU identifiers within the uploaded batch file.")
        instructions.append(
            "Enforce uniqueness constraint on SKU column before file export. Each product SKU must occur at most once per feed."
        )

    if has_price_err:
        root_causes.append("Invalid or unparseable unit_price values (negative numbers, exceeding 2 decimals, or non-numeric tokens).")
        instructions.append(
            "Format unit_price as positive decimal numbers with at most 2 decimal places (e.g. '19.99'). Strip unsupported currency codes or text."
        )

    if has_stock_err:
        root_causes.append("Invalid stock_quantity values (negative numbers, floating point values, or missing values).")
        instructions.append(
            "Verify stock_quantity is an integer greater than or equal to 0. Floating-point fractions and negative stock values are rejected."
        )

    if has_required_err:
        root_causes.append("Missing mandatory fields (SKU, name, category, or stock_quantity).")
        instructions.append(
            "Ensure every record includes populated values for required columns: 'sku', 'name', 'category', 'stock_quantity', and 'unit_price'."
        )

    if not root_causes:
        root_causes.append("Input records failed schema validation or row formatting rules.")
        instructions.append("Review error logs and verify feed structure matches the expected OmniFeed specifications.")

    summary = (
        f"Supplier feed '{job.filename}' achieved a health score of {health_score}/100. "
        f"{failed} of {total} record(s) failed validation. Primary bottlenecks: {', '.join(root_causes[:2])}."
    )

    return {
        "job_id": job.id,
        "filename": job.filename,
        "file_type": job.file_type,
        "status": job.status,
        "records_processed": total,
        "records_inserted": job.records_inserted,
        "records_updated": job.records_updated,
        "records_failed": failed,
        "health_score": health_score,
        "summary": summary,
        "root_causes": root_causes,
        "actionable_vendor_instructions": instructions,
        "error_breakdown": error_breakdown,
        "sample_errors": sample_errors,
    }


def generate_supplier_diagnostic(db: Session, job_id: int) -> dict[str, Any]:
    """
    Fetch ingestion errors for the job and generate an AI-powered diagnostic.
    Analyzes root causes, assigns a supplier data health score (0-100),
    and provides actionable vendor instructions.
    """
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

    error_breakdown: dict[str, int] = {}
    for err in errors:
        code = err.error_code or "VALIDATION_ERROR"
        error_breakdown[code] = error_breakdown.get(code, 0) + 1

    sample_errors = [
        {
            "row_number": err.row_number,
            "sku": err.sku,
            "error_code": err.error_code,
            "error_message": err.error_message,
        }
        for err in errors[:25]
    ]

    settings = get_settings()
    api_key = settings.gemini_api_key.strip() if settings.gemini_api_key else ""

    if not api_key:
        logger.info("GEMINI_API_KEY is not configured; using deterministic diagnostic engine.")
        return _rule_based_diagnostic(job, errors, error_breakdown, sample_errors)

    try:
        client = genai.Client(api_key=api_key)

        prompt = (
            f"Ingestion Job Metadata:\n"
            f"- Job ID: {job.id}\n"
            f"- Filename: {job.filename}\n"
            f"- File Type: {job.file_type}\n"
            f"- Status: {job.status}\n"
            f"- Processed Records: {job.records_processed}\n"
            f"- Inserted Records: {job.records_inserted}\n"
            f"- Updated Records: {job.records_updated}\n"
            f"- Failed Records: {job.records_failed}\n\n"
            f"Error Category Breakdown:\n{json.dumps(error_breakdown, indent=2)}\n\n"
            f"Sample Row Errors ({len(sample_errors)} of {len(errors)} total errors):\n"
            f"{json.dumps(sample_errors, indent=2)}\n\n"
            "Analyze these data errors and produce a comprehensive supplier data diagnostic. "
            "Return a JSON object with exactly the following keys:\n"
            "{\n"
            '  "health_score": <integer from 0 to 100 representing data compliance and quality>,\n'
            '  "summary": "<concise executive summary of feed quality and impact>",\n'
            '  "root_causes": ["<identified root cause 1>", "<identified root cause 2>", ...],\n'
            '  "actionable_vendor_instructions": ["<instruction 1 for supplier data engineering team>", "<instruction 2>", ...]\n'
            "}"
        )

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        )

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=config,
        )

        if response and response.text:
            parsed = json.loads(response.text)
            if isinstance(parsed, dict) and "health_score" in parsed:
                return {
                    "job_id": job.id,
                    "filename": job.filename,
                    "file_type": job.file_type,
                    "status": job.status,
                    "records_processed": job.records_processed,
                    "records_inserted": job.records_inserted,
                    "records_updated": job.records_updated,
                    "records_failed": job.records_failed,
                    "health_score": int(parsed.get("health_score", 50)),
                    "summary": str(parsed.get("summary", "")),
                    "root_causes": [str(c) for c in parsed.get("root_causes", [])],
                    "actionable_vendor_instructions": [
                        str(i) for i in parsed.get("actionable_vendor_instructions", [])
                    ],
                    "error_breakdown": error_breakdown,
                    "sample_errors": sample_errors,
                }

        logger.warning("Gemini diagnostic returned unexpected structure; using rule-based diagnostic.")
        return _rule_based_diagnostic(job, errors, error_breakdown, sample_errors)

    except Exception as exc:
        logger.warning("Gemini diagnostic encountered an error (%s); falling back to rule-based diagnostic.", exc)
        return _rule_based_diagnostic(job, errors, error_breakdown, sample_errors)
