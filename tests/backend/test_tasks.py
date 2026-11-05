"""
Tests for task API endpoints (/api/tasks).
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def clean_tasks():
    """Tasks live in a module-level list; clear it so tests stay independent."""
    mock_data.tasks.clear()
    yield
    mock_data.tasks.clear()


def make_task(client, **overrides):
    payload = {"title": "Check stock", "priority": "high", "dueDate": "2025-10-08", **overrides}
    return client.post("/api/tasks", json=payload)


class TestTaskEndpoints:
    """Test suite for task-related endpoints."""

    def test_get_tasks_initially_empty(self, client):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        response = make_task(client)
        assert response.status_code == 201

        task = response.json()
        assert task["title"] == "Check stock"
        assert task["priority"] == "high"
        assert task["dueDate"] == "2025-10-08"
        assert task["status"] == "pending"

    def test_task_id_is_string_not_numeric(self, client):
        """The client's demo tasks use numeric ids; API ids must never collide with them."""
        task = make_task(client).json()
        assert isinstance(task["id"], str)
        assert not task["id"].isdigit()

    def test_create_task_trims_title(self, client):
        assert make_task(client, title="  Review PO  ").json()["title"] == "Review PO"

    def test_get_tasks_newest_first(self, client):
        make_task(client, title="first")
        make_task(client, title="second")
        titles = [t["title"] for t in client.get("/api/tasks").json()]
        assert titles == ["second", "first"]

    def test_ids_stay_unique_after_delete(self, client):
        first = make_task(client).json()
        client.delete(f"/api/tasks/{first['id']}")
        second = make_task(client).json()
        third = make_task(client).json()
        assert len({first["id"], second["id"], third["id"]}) == 3

    def test_toggle_task(self, client):
        task_id = make_task(client).json()["id"]

        response = client.patch(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        assert client.patch(f"/api/tasks/{task_id}").json()["status"] == "pending"

    def test_delete_task(self, client):
        task_id = make_task(client).json()["id"]

        response = client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_toggle_nonexistent_task(self, client):
        response = client.patch("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_nonexistent_task(self, client):
        response = client.delete("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.parametrize("overrides", [
        {"title": "   "},
        {"title": ""},
        {"priority": "urgent"},
        {"dueDate": "next tuesday"},
        {"dueDate": "2025-13-45"},
    ])
    def test_invalid_task_rejected(self, client, overrides):
        assert make_task(client, **overrides).status_code == 422

    def test_missing_due_date_rejected(self, client):
        assert client.post("/api/tasks", json={"title": "x", "priority": "low"}).status_code == 422
