from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Category, InventoryItem
from app.services.ingestion import (
    clean_string,
    ingest_records,
    normalize_record,
    parse_price,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    yield session
    session.close()


def test_clean_string():
    assert clean_string("  hello  ") == "hello"
    assert clean_string(None) == ""
    assert clean_string(123) == "123"


def test_parse_price():
    assert parse_price("$12.50") == Decimal("12.50")
    assert parse_price("12.50 INR") == Decimal("12.50")
    assert parse_price(" $1,250.75 ") == Decimal("1250.75")
    assert parse_price(15) == Decimal("15.00")
    assert parse_price("10.5") == Decimal("10.50")

    with pytest.raises(ValueError, match="unit_price must be greater than zero"):
        parse_price("0.00")

    with pytest.raises(ValueError, match="unit_price must be greater than zero"):
        parse_price("-5.00")

    with pytest.raises(ValueError, match="unit_price supports at most 2 decimal places"):
        parse_price("12.555")

    with pytest.raises(ValueError, match="Invalid unit_price"):
        parse_price("free")


def test_normalize_record():
    valid_row = {
        "SKU": "SKU-100",
        "NAME": "Wireless Headphones",
        "category": "Audio",
        "stock_quantity": "25",
        "unit_price": "$99.99",
    }
    normalized = normalize_record(valid_row)
    assert normalized["sku"] == "SKU-100"
    assert normalized["name"] == "Wireless Headphones"
    assert normalized["category"] == "Audio"
    assert normalized["stock_quantity"] == 25
    assert normalized["unit_price"] == Decimal("99.99")

    # Missing SKU
    with pytest.raises(ValueError, match="sku is required"):
        normalize_record({**valid_row, "SKU": ""})

    # Negative stock
    with pytest.raises(ValueError, match="stock_quantity cannot be negative"):
        normalize_record({**valid_row, "stock_quantity": "-1"})

    # Non-integer stock
    with pytest.raises(ValueError, match="stock_quantity must be an integer"):
        normalize_record({**valid_row, "stock_quantity": "3.5"})


def test_ingest_records_upsert_and_duplicates(db_session):
    records = [
        {"sku": "SKU-1", "name": "Item 1", "category": "Tech", "stock_quantity": "10", "unit_price": "$15.00"},
        {"sku": "SKU-2", "name": "Item 2", "category": "Office", "stock_quantity": "5", "unit_price": "25.00 INR"},
        {"sku": "SKU-1", "name": "Item 1 Duplicate", "category": "Tech", "stock_quantity": "10", "unit_price": "$15.00"},
        {"sku": "SKU-3", "name": "Invalid Item", "category": "Tech", "stock_quantity": "-5", "unit_price": "$10.00"},
    ]

    summary = ingest_records(db_session, records, filename="test.csv", file_type="csv")

    assert summary["status"] == "completed_with_errors"
    assert summary["records_processed"] == 4
    assert summary["records_inserted"] == 2  # SKU-1, SKU-2
    assert summary["records_updated"] == 0
    assert summary["records_failed"] == 2  # Duplicate SKU-1, negative stock for SKU-3
    assert len(summary["errors"]) == 2

    # Check categories created
    cats = db_session.query(Category).all()
    cat_names = {c.name for c in cats}
    assert "Tech" in cat_names
    assert "Office" in cat_names

    # Check items inserted
    items = db_session.query(InventoryItem).all()
    assert len(items) == 2

    # Ingest again with update for SKU-1 and new SKU-4
    update_records = [
        {"sku": "SKU-1", "name": "Item 1 Updated", "category": "Tech", "stock_quantity": "15", "unit_price": "$18.50"},
        {"sku": "SKU-4", "name": "Item 4", "category": "Tech", "stock_quantity": "20", "unit_price": "$30.00"},
    ]

    second_summary = ingest_records(db_session, update_records, filename="update.csv", file_type="csv")
    assert second_summary["status"] == "completed"
    assert second_summary["records_inserted"] == 1
    assert second_summary["records_updated"] == 1
    assert second_summary["records_failed"] == 0

    item_1 = db_session.query(InventoryItem).filter_by(sku="SKU-1").first()
    assert item_1.name == "Item 1 Updated"
    assert item_1.stock_quantity == 15
    assert item_1.unit_price == Decimal("18.50")


def test_ingest_invalid_sample_csv(db_session):
    from pathlib import Path
    from app.parsers import CSVParser

    sample_path = Path(__file__).resolve().parent.parent / "sample_data" / "invalid_sample.csv"
    assert sample_path.exists()

    content = sample_path.read_bytes()
    parser = CSVParser()
    records = parser.parse(content)

    summary = ingest_records(db_session, records, filename="invalid_sample.csv", file_type="csv")
    assert summary["status"] == "completed_with_errors"
    assert summary["records_processed"] == 4
    assert summary["records_inserted"] == 1  # SKU-9001
    assert summary["records_failed"] == 3    # duplicate SKU-9001, negative stock, invalid price
    assert len(summary["errors"]) == 3


def test_ingest_accessories_catalog_csv(db_session):
    from pathlib import Path
    from app.parsers import CSVParser

    sample_path = Path(__file__).resolve().parent.parent / "sample_data" / "accessories_catalog.csv"
    assert sample_path.exists()

    content = sample_path.read_bytes()
    parser = CSVParser()
    records = list(parser.parse(content))

    assert len(records) == 10

    summary = ingest_records(db_session, records, filename="accessories_catalog.csv", file_type="csv")
    assert summary["status"] == "completed"
    assert summary["records_processed"] == 10
    assert summary["records_inserted"] == 10
    assert summary["records_updated"] == 0
    assert summary["records_failed"] == 0
    assert len(summary["errors"]) == 0

    # Validate categories
    categories = {c.name for c in db_session.query(Category).all()}
    expected_categories = {"Costume Jewellery", "Scarves & Stoles", "Leather Goods", "Hair Accessories"}
    assert expected_categories.issubset(categories)

    # Validate stock distributions
    items = db_session.query(InventoryItem).all()
    assert len(items) == 10

    well_stocked = [i for i in items if i.stock_quantity > 100]
    assert len(well_stocked) >= 2

    low_stock = [i for i in items if 0 < i.stock_quantity < 10]
    assert len(low_stock) >= 2

    out_of_stock = [i for i in items if i.stock_quantity == 0]
    assert len(out_of_stock) >= 1

    # Validate prices are positive decimals
    for item in items:
        assert isinstance(item.unit_price, Decimal)
        assert item.unit_price > Decimal("0.00")


def test_ingest_corrupt_feed_csv(db_session):
    from pathlib import Path
    from app.parsers import CSVParser

    sample_path = Path(__file__).resolve().parent.parent / "sample_data" / "corrupt_feed.csv"
    assert sample_path.exists()

    content = sample_path.read_bytes()
    parser = CSVParser()
    records = list(parser.parse(content))

    assert len(records) == 5

    summary = ingest_records(db_session, records, filename="corrupt_feed.csv", file_type="csv")
    assert summary["status"] == "completed_with_errors"
    assert summary["records_processed"] == 5
    assert summary["records_inserted"] == 1  # Only 1 valid item (ERR-101)
    assert summary["records_failed"] == 4
    assert len(summary["errors"]) == 4

    error_messages = [e["error_message"] for e in summary["errors"]]
    # Negative stock
    assert any("stock_quantity cannot be negative" in msg for msg in error_messages)
    # Invalid price ($0.00)
    assert any("unit_price must be greater than zero" in msg for msg in error_messages)
    # Duplicate SKU
    assert any("Duplicate SKU 'ERR-101'" in msg for msg in error_messages)
    # Missing mandatory name field
    assert any("name is required" in msg for msg in error_messages)


def test_seed_demo_data_script():
    from scripts.seed_demo_data import seed_demo_data
    from sqlalchemy.exc import OperationalError

    try:
        result = seed_demo_data()
        assert result["status"] == "completed"
        assert result["records_processed"] == 10
        assert result["records_failed"] == 0
        assert result["total_items"] >= 10
        assert result["execution_time_seconds"] > 0
    except OperationalError as exc:
        pytest.skip(f"Database network connection unavailable: {exc}")


