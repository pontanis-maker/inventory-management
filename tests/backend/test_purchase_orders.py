"""
Tests for purchase order API endpoints (/api/purchase-orders).
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def clean_purchase_orders():
    """Purchase orders live in a module-level list; clear it so tests stay independent."""
    mock_data.purchase_orders.clear()
    yield
    mock_data.purchase_orders.clear()


@pytest.fixture
def backlog_id(client):
    """A real backlog item id."""
    return client.get("/api/backlog").json()[0]["id"]


def make_po(client, backlog_item_id, **overrides):
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Acme Supply",
        "quantity": 400,
        "unit_cost": 8.4,
        "expected_delivery_date": "2025-11-15",
        "notes": "Rush",
        **overrides,
    }
    return client.post("/api/purchase-orders", json=payload)


class TestPurchaseOrderEndpoints:
    """Test suite for purchase order endpoints."""

    def test_create_purchase_order(self, client, backlog_id):
        response = make_po(client, backlog_id)
        assert response.status_code == 201

        po = response.json()
        assert po["backlog_item_id"] == backlog_id
        assert po["supplier_name"] == "Acme Supply"
        assert po["quantity"] == 400
        assert po["unit_cost"] == 8.4
        assert po["status"] == "Pending"
        assert po["notes"] == "Rush"
        assert "T" in po["created_date"]
        assert po["id"]

    def test_get_purchase_order_by_backlog_item(self, client, backlog_id):
        created = make_po(client, backlog_id).json()

        response = client.get(f"/api/purchase-orders/{backlog_id}")
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_get_purchase_order_when_none_exists(self, client, backlog_id):
        response = client.get(f"/api/purchase-orders/{backlog_id}")
        assert response.status_code == 404
        assert "no purchase order" in response.json()["detail"].lower()

    def test_backlog_flag_reflects_purchase_order(self, client, backlog_id):
        """GET /api/backlog derives has_purchase_order from the purchase order list."""
        def flag():
            return next(i for i in client.get("/api/backlog").json() if i["id"] == backlog_id)["has_purchase_order"]

        assert flag() is False
        make_po(client, backlog_id)
        assert flag() is True

    def test_unknown_backlog_item_rejected(self, client):
        response = make_po(client, "nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert mock_data.purchase_orders == []

    def test_duplicate_purchase_order_rejected(self, client, backlog_id):
        assert make_po(client, backlog_id).status_code == 201
        response = make_po(client, backlog_id, supplier_name="Other")
        assert response.status_code == 409
        assert len(mock_data.purchase_orders) == 1

    def test_purchase_order_without_notes(self, client, backlog_id):
        payload = {"backlog_item_id": backlog_id, "supplier_name": "Acme", "quantity": 1,
                   "unit_cost": 1.0, "expected_delivery_date": "2025-11-15"}
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 201
        assert response.json()["notes"] is None

    @pytest.mark.parametrize("overrides", [
        {"quantity": 0},
        {"quantity": -5},
        {"unit_cost": -1},
        {"supplier_name": ""},
        {"expected_delivery_date": "soon"},
    ])
    def test_invalid_purchase_order_rejected(self, client, backlog_id, overrides):
        assert make_po(client, backlog_id, **overrides).status_code == 422
