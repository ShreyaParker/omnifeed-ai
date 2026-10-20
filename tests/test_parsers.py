from decimal import Decimal
from pathlib import Path
import pytest

from app.parsers import CSVParser, JSONParser, XMLParser
from app.services.ingestion import normalize_record, parse_price

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


# --- Parser Tests ---

def test_csv_parser_with_sample_file():
    sample_file = SAMPLE_DIR / "sample.csv"
    assert sample_file.exists(), f"Missing {sample_file}"
    content = sample_file.read_bytes()

    parser = CSVParser()
    rows = list(parser.parse(content))
    assert len(rows) == 5
    assert rows[0]["sku"] == "SKU-1001"
    assert rows[0]["name"] == "Wireless Ergonomic Mouse"
    assert rows[0]["category"] == "Electronics"
    assert rows[0]["stock_quantity"] == "45"
    assert rows[0]["unit_price"] == "$24.99"
    assert rows[4]["sku"] == "SKU-1005"
    assert rows[4]["unit_price"] == "$12.50"


def test_csv_parser_empty():
    parser = CSVParser()
    with pytest.raises(ValueError, match="CSV file is empty"):
        list(parser.parse(b""))


def test_json_parser_with_sample_file():
    sample_file = SAMPLE_DIR / "sample.json"
    assert sample_file.exists(), f"Missing {sample_file}"
    content = sample_file.read_bytes()

    parser = JSONParser()
    rows = list(parser.parse(content))
    assert len(rows) == 3
    assert rows[0]["sku"] == "SKU-2001"
    assert rows[0]["name"] == "Noise Cancelling Headphones"
    assert rows[1]["sku"] == "SKU-2002"
    assert rows[1]["unit_price"] == "299.50 INR"
    assert rows[2]["sku"] == "SKU-2003"


def test_json_parser_invalid():
    parser = JSONParser()
    with pytest.raises(ValueError, match="Invalid JSON"):
        list(parser.parse(b"{bad json"))


def test_xml_parser_with_sample_file():
    sample_file = SAMPLE_DIR / "sample.xml"
    assert sample_file.exists(), f"Missing {sample_file}"
    content = sample_file.read_bytes()

    parser = XMLParser()
    rows = list(parser.parse(content))
    assert len(rows) == 2
    assert rows[0]["sku"] == "SKU-3001"
    assert rows[0]["name"] == "Ultra-Wide 4K Monitor"
    assert rows[0]["stock_quantity"] == "12"
    assert rows[0]["unit_price"] == "$499.00"
    assert rows[1]["sku"] == "SKU-3002"
    assert rows[1]["unit_price"] == "42.50 USD"


def test_xml_parser_invalid():
    parser = XMLParser()
    with pytest.raises(ValueError, match="Invalid or unsafe XML"):
        list(parser.parse(b"<items><item><sku>Unterminated</item>"))


# --- parse_price Unit Tests ---

def test_parse_price_formats():
    # Standard dollar format
    assert parse_price("$12.50") == Decimal("12.50")
    # INR format
    assert parse_price("12.50 INR") == Decimal("12.50")
    # USD format
    assert parse_price("42.50 USD") == Decimal("42.50")
    # Comma separation and surrounding whitespace
    assert parse_price("  $1,250.75  ") == Decimal("1250.75")
    # Clean float or integer inputs
    assert parse_price(15) == Decimal("15.00")
    assert parse_price("10.5") == Decimal("10.50")


def test_parse_price_invalid_strings():
    with pytest.raises(ValueError, match="Invalid unit_price"):
        parse_price("FREE")

    with pytest.raises(ValueError, match="Invalid unit_price"):
        parse_price("")

    with pytest.raises(ValueError, match="Invalid unit_price"):
        parse_price(None)

    with pytest.raises(ValueError, match="unit_price must be greater than zero"):
        parse_price("0.00")

    with pytest.raises(ValueError, match="unit_price must be greater than zero"):
        parse_price("-$10.00")

    with pytest.raises(ValueError, match="unit_price supports at most 2 decimal places"):
        parse_price("12.555")


# --- normalize_record Unit Tests ---

def test_normalize_record_valid_structure():
    raw = {
        "sku": "SKU-TEST-01",
        "name": "Standard Laptop",
        "category": "Electronics",
        "stock_quantity": "30",
        "unit_price": "$899.00",
    }
    normalized = normalize_record(raw)
    assert normalized == {
        "sku": "SKU-TEST-01",
        "name": "Standard Laptop",
        "category": "Electronics",
        "stock_quantity": 30,
        "unit_price": Decimal("899.00"),
    }


def test_normalize_record_whitespace_stripping():
    raw = {
        "  SKU  ": "  SKU-SPACES-99  ",
        "  NAME ": "  Space Cadet Notebook  ",
        "  CATEGORY ": "  Stationery  ",
        " stock_quantity ": " 50 ",
        " unit_price ": " $12.50 ",
    }
    normalized = normalize_record(raw)
    assert normalized["sku"] == "SKU-SPACES-99"
    assert normalized["name"] == "Space Cadet Notebook"
    assert normalized["category"] == "Stationery"
    assert normalized["stock_quantity"] == 50
    assert normalized["unit_price"] == Decimal("12.50")


def test_normalize_record_rejection_of_negative_stock():
    raw = {
        "sku": "SKU-NEG",
        "name": "Negative Item",
        "category": "Electronics",
        "stock_quantity": "-10",
        "unit_price": "$20.00",
    }
    with pytest.raises(ValueError, match="stock_quantity cannot be negative"):
        normalize_record(raw)


def test_normalize_record_missing_required_fields():
    with pytest.raises(ValueError, match="sku is required"):
        normalize_record({"sku": "", "name": "Item", "category": "Cat", "stock_quantity": 10, "unit_price": 10})

    with pytest.raises(ValueError, match="name is required"):
        normalize_record({"sku": "SKU-1", "name": "   ", "category": "Cat", "stock_quantity": 10, "unit_price": 10})

    with pytest.raises(ValueError, match="category is required"):
        normalize_record({"sku": "SKU-1", "name": "Item", "category": "", "stock_quantity": 10, "unit_price": 10})
