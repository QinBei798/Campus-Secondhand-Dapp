"""TDD test suite for relay layer — DB, listener event parsing, and FastAPI endpoints.

RED phase: all tests written against modules not yet implemented (listener, main).
"""
import os
import sys
import json
import pytest

# Ensure relay package is importable from project root
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from relay.db import (
    init_db,
    get_connection,
    upsert_order,
    upsert_order_partial,
    upsert_dispute,
    update_dispute_votes,
    get_last_synced_block,
    update_sync_block,
    get_orders,
    get_order,
    get_disputes,
    create_dispute,
    insert_tx_history,
    get_tx_history_by_order,
)

TEST_DB = os.path.join(os.path.dirname(__file__), "test_relay.db")


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    """Isolate each test with a clean test database."""
    monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    init_db()
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


# ================================================================
# Suite A: Database Layer Tests
# ================================================================

class TestDatabase:
    def test_init_db_creates_tables(self):
        conn = get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        names = [t["name"] for t in tables]
        assert "orders" in names
        assert "disputes" in names
        assert "sync_state" in names

    def test_sync_state_defaults_to_zero(self):
        assert get_last_synced_block() == 0

    def test_update_sync_block(self):
        update_sync_block(42)
        assert get_last_synced_block() == 42

    def test_upsert_order_insert(self):
        upsert_order(0, "0xBuyer", "0xSeller", 1000000, "CREATED", "Laptop")
        orders = get_orders()
        assert len(orders) == 1
        assert orders[0]["state"] == "CREATED"
        assert orders[0]["buyer"] == "0xBuyer"

    def test_upsert_order_update_state(self):
        upsert_order(0, "0xBuyer", "0xSeller", 1000000, "CREATED", "Laptop")
        # Subsequent call with same contract_id updates state
        upsert_order(0, "0xBuyer", "0xSeller", 1000000, "FUNDED", "Laptop")
        orders = get_orders()
        assert len(orders) == 1
        assert orders[0]["state"] == "FUNDED"

    def test_upsert_order_partial_preserves_existing_columns(self):
        upsert_order(1, "0xBuyer", "0xSeller", 5000000, "CREATED", "iPhone")
        upsert_order_partial(1, "FUNDED")
        order = get_order(1)
        assert order["state"] == "FUNDED"
        # Partial update should not zero out buyer/seller (ON CONFLICT preserves)
        assert order["buyer"] == "0xBuyer"

    def test_get_orders_filter_by_state(self):
        upsert_order(0, "0xA", "0xB", 1000, "CREATED", "")
        upsert_order(1, "0xC", "0xD", 2000, "FUNDED", "")
        assert len(get_orders("CREATED")) == 1
        assert len(get_orders("FUNDED")) == 1
        assert len(get_orders()) == 2

    def test_get_order_by_id_found_and_not_found(self):
        upsert_order(5, "0xA", "0xB", 500, "SHIPPED", "Book")
        o = get_order(5)
        assert o is not None
        assert o["state"] == "SHIPPED"
        assert get_order(999) is None

    def test_upsert_dispute_creates_record(self):
        upsert_dispute(0, 0, "Item broken")
        disputes = get_disputes()
        assert len(disputes) == 1
        assert disputes[0]["reason"] == "Item broken"

    def test_update_dispute_votes_set_resolved(self):
        upsert_dispute(0, 0, "Fake item")
        update_dispute_votes(0, votes_for_buyer=2, votes_for_seller=0, resolved=1)
        disputes = get_disputes()
        assert disputes[0]["votes_for_buyer"] == 2
        assert disputes[0]["resolved"] == 1
        assert disputes[0]["resolved_at"] is not None

    def test_create_dispute_standalone(self):
        create_dispute(0, 0, "Not delivered")
        disputes = get_disputes()
        assert len(disputes) == 1

    def test_order_tx_history_operations(self):
        insert_tx_history(1, "CREATED", "0x1111", 100)
        insert_tx_history(1, "FUNDED", "0x2222", 105)
        # test duplicate prevention
        insert_tx_history(1, "CREATED", "0x3333", 110)
        
        history = get_tx_history_by_order(1)
        assert len(history) == 2
        assert history[0]["action"] == "CREATED"
        assert history[0]["tx_hash"] == "0x1111"
        assert history[0]["block_number"] == 100
        assert history[1]["action"] == "FUNDED"
        assert history[1]["tx_hash"] == "0x2222"
        assert history[1]["block_number"] == 105


# ================================================================
# Suite B: Listener Event Parsing Tests
# ================================================================

class TestListenerEventParsing:
    def test_parse_order_created_event(self, monkeypatch):
        monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
        init_db()

        from relay.listener import handle_order_created

        mock_event = type("Event", (), {
            "args": {
                "orderId": 0,
                "seller": "0xSellerAddr",
                "buyer": "0xBuyerAddr",
                "amount": 1000000000000000000,
            }
        })()
        handle_order_created(mock_event)
        order = get_order(0)
        assert order is not None
        assert order["buyer"] == "0xBuyerAddr"
        assert order["seller"] == "0xSellerAddr"
        assert order["state"] == "CREATED"

    def test_parse_order_funded_event(self, monkeypatch):
        monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
        init_db()

        from relay.listener import handle_order_funded

        upsert_order(0, "0xBuyer", "0xSeller", "1000000", "CREATED", "")
        mock_event = type("Event", (), {
            "args": {"orderId": 0, "buyer": "0xBuyer", "amount": 1000000}
        })()
        handle_order_funded(mock_event)
        order = get_order(0)
        assert order["state"] == "FUNDED"

    def test_parse_order_shipped_event(self, monkeypatch):
        monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
        init_db()

        from relay.listener import handle_order_shipped

        upsert_order(0, "0xBuyer", "0xSeller", "1000000", "FUNDED", "")
        mock_event = type("Event", (), {
            "args": {"orderId": 0, "timestamp": 1718352000}
        })()
        handle_order_shipped(mock_event)
        order = get_order(0)
        assert order["state"] == "SHIPPED"

    def test_parse_order_received_event(self, monkeypatch):
        monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
        init_db()

        from relay.listener import handle_order_received

        upsert_order(0, "0xBuyer", "0xSeller", "1000000", "SHIPPED", "")
        mock_event = type("Event", (), {
            "args": {"orderId": 0, "timestamp": 1718353000}
        })()
        handle_order_received(mock_event)
        order = get_order(0)
        assert order["state"] == "COMPLETED"

    def test_parse_order_disputed_event(self, monkeypatch):
        monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
        init_db()

        from relay.listener import handle_order_disputed

        upsert_order(0, "0xBuyer", "0xSeller", "1000000", "FUNDED", "")
        mock_event = type("Event", (), {
            "args": {"orderId": 0, "initiator": "0xBuyer"}
        })()
        handle_order_disputed(mock_event)
        order = get_order(0)
        assert order["state"] == "DISPUTED"


# ================================================================
# Suite C: FastAPI Endpoint Tests
# ================================================================

@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setattr("relay.db.DB_PATH", TEST_DB)
    init_db()
    from relay.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestAPIEndpoints:
    def test_health_check(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_get_orders_empty(self, api_client):
        resp = api_client.get("/api/orders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_orders_with_data(self, api_client):
        upsert_order(0, "0xBuyer", "0xSeller", "1000", "CREATED", "Item")
        upsert_order(1, "0xB2", "0xS2", "2000", "FUNDED", "Item2")
        resp = api_client.get("/api/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_get_orders_filter_state(self, api_client):
        upsert_order(0, "0xB", "0xS", "1000", "CREATED", "")
        upsert_order(1, "0xB2", "0xS2", "2000", "FUNDED", "")
        resp = api_client.get("/api/orders?state=FUNDED")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["state"] == "FUNDED"

    def test_get_order_by_contract_id(self, api_client):
        upsert_order(7, "0xBuyer7", "0xSeller7", "777", "SHIPPED", "Test")
        resp = api_client.get("/api/orders/7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_id"] == 7
        assert data["state"] == "SHIPPED"

    def test_get_order_not_found(self, api_client):
        resp = api_client.get("/api/orders/999")
        assert resp.status_code == 404

    def test_get_disputes_empty(self, api_client):
        resp = api_client.get("/api/disputes")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_disputes_with_data(self, api_client):
        upsert_dispute(0, 0, "Bad item")
        resp = api_client.get("/api/disputes")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_post_dispute_creates_record(self, api_client):
        upsert_order(0, "0xB", "0xS", "1000", "FUNDED", "")
        resp = api_client.post("/api/disputes", json={
            "order_id": 0, "reason": "Item not as described"
        })
        assert resp.status_code == 201
        disputes = get_disputes()
        assert len(disputes) == 1

    def test_get_whitelist_proof_known_address(self, api_client):
        """Known Hardhat address #2 (seller in the test suite) returns valid Merkle proof."""
        resp = api_client.get("/api/whitelist/proof/0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC")
        assert resp.status_code == 200
        data = resp.json()
        assert "proof" in data
        assert "leaf" in data
        assert "root" in data
        assert len(data["proof"]) > 0

    def test_get_whitelist_proof_unknown_address(self, api_client):
        resp = api_client.get("/api/whitelist/proof/0x0000000000000000000000000000000000000001")
        assert resp.status_code == 404

    def test_get_order_includes_history(self, api_client):
        from relay.db import insert_tx_history
        upsert_order(10, "0xBuyer", "0xSeller", "1000", "CREATED", "Laptop")
        insert_tx_history(10, "CREATED", "0x1111", 100)
        
        resp = api_client.get("/api/orders/10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["history"]) == 1
        assert data["history"][0]["action"] == "CREATED"
        assert data["history"][0]["tx_hash"] == "0x1111"
        assert data["history"][0]["block_number"] == 100

    def test_get_tx_details_mock(self, api_client):
        resp = api_client.get("/api/tx/0xabc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == 1
        assert data["block_number"] == 1583
        assert data["gas_used"] == 45120
