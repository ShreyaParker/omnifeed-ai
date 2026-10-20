from unittest.mock import MagicMock, patch
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Category, InventoryItem
from app.services.embedding_service import (
    batch_embed_items,
    generate_embedding,
    generate_item_text,
)
from app.services.ingestion import ingest_records


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    yield session
    session.close()


def test_generate_item_text():
    text = generate_item_text("Wireless Mouse", "Electronics", "SKU-WM-01")
    assert text == "Product: Wireless Mouse | Category: Electronics | SKU: SKU-WM-01"

    # Handles whitespace and None
    text_none = generate_item_text(None, " Office ", "")
    assert text_none == "Product:  | Category: Office | SKU: "


def test_generate_embedding_missing_api_key(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "")

    result = generate_embedding("Some product text")
    assert result is None


def test_generate_embedding_empty_text():
    result = generate_embedding("   ")
    assert result is None


def test_generate_embedding_success(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "test_key")

    mock_values = [0.1, 0.2, 0.3]
    mock_embedding = MagicMock()
    mock_embedding.values = mock_values
    mock_response = MagicMock()
    mock_response.embeddings = [mock_embedding]

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_response
        mock_client_cls.return_value = mock_client

        vector = generate_embedding("Product: Phone")
        assert vector == mock_values
        mock_client.models.embed_content.assert_called_once_with(
            model=settings.embedding_model,
            contents="Product: Phone",
        )


def test_generate_embedding_error_handling(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "test_key")

    with patch("google.genai.Client", side_effect=Exception("API failure")):
        vector = generate_embedding("Product: Phone")
        assert vector is None


def test_batch_embed_items(db_session):
    cat = Category(name="Electronics")
    db_session.add(cat)
    db_session.flush()

    item1 = InventoryItem(
        sku="SKU-E1",
        name="Laptop",
        category_id=cat.id,
        stock_quantity=10,
        unit_price=Decimal("999.00"),
        embedding=None,
    )
    item2 = InventoryItem(
        sku="SKU-E2",
        name="Mouse",
        category_id=cat.id,
        stock_quantity=50,
        unit_price=Decimal("25.00"),
        embedding=[0.5] * 768,  # Already has embedding
    )
    item3 = InventoryItem(
        sku="SKU-E3",
        name="Keyboard",
        category_id=cat.id,
        stock_quantity=20,
        unit_price=Decimal("45.00"),
        embedding=None,
    )
    db_session.add_all([item1, item2, item3])
    db_session.commit()

    fake_vector = [0.123] * 768
    with patch("app.services.embedding_service.generate_embedding", return_value=fake_vector) as mock_gen:
        updated = batch_embed_items(db_session, limit=10)
        assert updated == 2
        assert mock_gen.call_count == 2

    # Refresh items from DB and verify embeddings
    db_session.expire_all()
    reloaded_item1 = db_session.query(InventoryItem).filter_by(sku="SKU-E1").first()
    reloaded_item2 = db_session.query(InventoryItem).filter_by(sku="SKU-E2").first()
    reloaded_item3 = db_session.query(InventoryItem).filter_by(sku="SKU-E3").first()

    assert reloaded_item1.embedding == fake_vector
    assert reloaded_item2.embedding == [0.5] * 768
    assert reloaded_item3.embedding == fake_vector


def test_ingest_records_generates_and_assigns_embeddings(db_session):
    fake_vector = [0.42] * 768
    with patch("app.services.ingestion.generate_embedding", return_value=fake_vector) as mock_embed:
        records = [
            {"sku": "SKU-V1", "name": "Tablet", "category": "Gadgets", "stock_quantity": "12", "unit_price": "$299.99"},
        ]
        summary = ingest_records(db_session, records, filename="vec.csv", file_type="csv")
        assert summary["status"] == "completed"
        assert summary["records_inserted"] == 1
        assert mock_embed.called

        item = db_session.query(InventoryItem).filter_by(sku="SKU-V1").first()
        assert item is not None
        assert item.embedding == fake_vector

        # Now test update with a new vector
        updated_vector = [0.99] * 768
        mock_embed.return_value = updated_vector

        update_records = [
            {"sku": "SKU-V1", "name": "Tablet Pro", "category": "Gadgets", "stock_quantity": "15", "unit_price": "$349.99"},
        ]
        update_summary = ingest_records(db_session, update_records, filename="vec_up.csv", file_type="csv")
        assert update_summary["status"] == "completed"
        assert update_summary["records_updated"] == 1

        db_session.expire_all()
        reloaded_item = db_session.query(InventoryItem).filter_by(sku="SKU-V1").first()
        assert reloaded_item.name == "Tablet Pro"
        assert reloaded_item.embedding == updated_vector
