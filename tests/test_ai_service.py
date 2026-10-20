from app.services.ai_service import _rule_based_insights, generate_insights


def test_rule_based_insights_fallback():
    overview = {
        "total_skus": 25,
        "total_units": 150,
        "inventory_valuation": "15000.00",
        "low_stock_items": 3,
        "out_of_stock_items": 1,
    }
    alerts = [
        {"sku": "SKU-OUT", "name": "Out of Stock Item", "stock_quantity": 0, "category": "Tech"},
        {"sku": "SKU-LOW", "name": "Low Stock Item", "stock_quantity": 4, "category": "Office"},
    ]

    result = _rule_based_insights(overview, alerts)
    assert "summary" in result
    assert "recommendations" in result
    assert isinstance(result["summary"], str)
    assert isinstance(result["recommendations"], list)
    assert len(result["recommendations"]) >= 2
    assert "out-of-stock" in result["summary"].lower() or "out of stock" in result["summary"].lower()


def test_generate_insights_runs_safely():
    overview = {
        "total_skus": 10,
        "total_units": 80,
        "inventory_valuation": "5000.00",
        "low_stock_items": 1,
        "out_of_stock_items": 0,
    }
    alerts = [{"sku": "SKU-ALERT", "name": "Alert Item", "stock_quantity": 2, "category": "Tech"}]

    result = generate_insights(overview, alerts)
    assert "summary" in result
    assert "recommendations" in result
    assert isinstance(result["summary"], str)
    assert isinstance(result["recommendations"], list)
