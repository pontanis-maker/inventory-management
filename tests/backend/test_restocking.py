"""
Tests for restocking API endpoints (recommendations and submitted orders).
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def clean_restocking_orders():
    """Orders live in a module-level list; clear it so tests stay independent."""
    mock_data.restocking_orders.clear()
    yield
    mock_data.restocking_orders.clear()


class TestRestockRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_recommendations_structure(self, client):
        response = client.get("/api/restocking/recommendations?budget=100000")
        assert response.status_code == 200

        data = response.json()
        for key in ("budget", "total_cost", "remaining_budget", "items"):
            assert key in data
        assert len(data["items"]) > 0

        for item in data["items"]:
            for key in ("sku", "name", "category", "warehouse", "trend", "shortfall",
                        "unit_cost", "recommended_quantity", "line_total", "lead_time_days"):
                assert key in item

    def test_recommendations_never_exceed_budget(self, client):
        for budget in (0, 500, 5000, 50000, 500000):
            data = client.get(f"/api/restocking/recommendations?budget={budget}").json()
            assert data["total_cost"] <= budget
            assert abs(data["total_cost"] + data["remaining_budget"] - budget) < 0.01

    def test_recommended_quantity_capped_at_shortfall(self, client):
        data = client.get("/api/restocking/recommendations?budget=500000").json()
        for item in data["items"]:
            assert 0 <= item["recommended_quantity"] <= item["shortfall"]
            assert item["shortfall"] > 0
            assert abs(item["line_total"] - item["recommended_quantity"] * item["unit_cost"]) < 0.01

    def test_zero_budget_recommends_nothing(self, client):
        data = client.get("/api/restocking/recommendations?budget=0").json()
        assert data["total_cost"] == 0
        assert all(i["recommended_quantity"] == 0 for i in data["items"])

    def test_increasing_trend_funded_first(self, client):
        data = client.get("/api/restocking/recommendations?budget=100000").json()
        trends = [i["trend"] for i in data["items"]]
        order = {"increasing": 0, "stable": 1, "decreasing": 2}
        assert [order[t] for t in trends] == sorted(order[t] for t in trends)

    def test_items_without_shortfall_excluded(self, client):
        # PSU-501 has more stock on hand than forecast demand
        data = client.get("/api/restocking/recommendations?budget=500000").json()
        assert "PSU-501" not in {i["sku"] for i in data["items"]}

    def test_filter_by_category(self, client):
        data = client.get("/api/restocking/recommendations?budget=500000&category=Sensors").json()
        assert len(data["items"]) > 0
        assert all(i["category"] == "Sensors" for i in data["items"])

    def test_filter_by_warehouse(self, client):
        data = client.get("/api/restocking/recommendations?budget=500000&warehouse=Tokyo").json()
        assert len(data["items"]) > 0
        assert all(i["warehouse"] == "Tokyo" for i in data["items"])

    def test_negative_budget_rejected(self, client):
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 400


class TestRestockOrders:
    """Test suite for POST/GET /api/restocking-orders."""

    def test_create_order(self, client):
        payload = {"budget": 10000, "items": [{"sku": "WDG-001", "quantity": 100}]}
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["order_number"].startswith("RST-")
        assert order["status"] == "Submitted"
        assert order["total_cost"] == 4250.0  # 100 x 42.50 from the server catalog
        assert order["lead_time_days"] == 18  # Actuators
        assert order["items"][0]["lead_time_days"] == 18

    def test_expected_delivery_matches_lead_time(self, client):
        from datetime import datetime
        order = client.post("/api/restocking-orders", json={
            "budget": 10000, "items": [{"sku": "FLT-405", "quantity": 10}]}).json()
        placed = datetime.fromisoformat(order["order_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert (expected - placed).days == order["lead_time_days"] == 7

    def test_order_lead_time_is_longest_item(self, client):
        order = client.post("/api/restocking-orders", json={
            "budget": 50000,
            "items": [{"sku": "FLT-405", "quantity": 10},    # Sensors, 7 days
                      {"sku": "CTL-330", "quantity": 10}],   # Controllers, 21 days
        }).json()
        assert order["lead_time_days"] == 21

    def test_order_appears_in_list_newest_first(self, client):
        for sku in ("WDG-001", "GSK-203"):
            client.post("/api/restocking-orders", json={"budget": 10000, "items": [{"sku": sku, "quantity": 1}]})
        orders = client.get("/api/restocking-orders").json()
        assert [o["items"][0]["sku"] for o in orders] == ["GSK-203", "WDG-001"]
        assert orders[0]["order_number"] != orders[1]["order_number"]

    def test_empty_list_initially(self, client):
        assert client.get("/api/restocking-orders").json() == []

    def test_total_over_budget_rejected(self, client):
        response = client.post("/api/restocking-orders", json={
            "budget": 100, "items": [{"sku": "WDG-001", "quantity": 100}]})
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()
        assert client.get("/api/restocking-orders").json() == []

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking-orders", json={
            "budget": 10000, "items": [{"sku": "NOPE-000", "quantity": 1}]})
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        response = client.post("/api/restocking-orders", json={
            "budget": 10000, "items": [{"sku": "WDG-001", "quantity": 1}, {"sku": "WDG-001", "quantity": 2}]})
        assert response.status_code == 400

    @pytest.mark.parametrize("payload", [
        {"budget": 1000, "items": []},
        {"budget": 1000, "items": [{"sku": "WDG-001", "quantity": 0}]},
        {"budget": -5, "items": [{"sku": "WDG-001", "quantity": 1}]},
    ])
    def test_invalid_payload_rejected(self, client, payload):
        assert client.post("/api/restocking-orders", json=payload).status_code == 422
