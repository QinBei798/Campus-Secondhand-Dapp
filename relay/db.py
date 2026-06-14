"""SQLite database layer for off-chain relay — orders, disputes, sync state.

Constraint 1: sqlite3.connect with timeout=30.0 + check_same_thread=False
to prevent "database is locked" under concurrent read/write from listener
(background daemon thread) and FastAPI (main thread).
"""
import sqlite3
import os
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "relay.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER UNIQUE NOT NULL,
            buyer TEXT NOT NULL,
            seller TEXT NOT NULL,
            amount_wei TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'CREATED',
            description TEXT DEFAULT '',
            dispute_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER UNIQUE NOT NULL,
            order_id INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            votes_for_buyer INTEGER DEFAULT 0,
            votes_for_seller INTEGER DEFAULT 0,
            resolved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        INSERT OR IGNORE INTO sync_state (key, value) VALUES ('last_block', '0');
    """)
    conn.commit()
    conn.close()


# ─── Orders ────────────────────────────────────────────────────

def upsert_order(contract_id: int, buyer: str, seller: str,
                 amount_wei: int, state: str, description: str = "",
                 dispute_id: int = 0) -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO orders (contract_id, buyer, seller, amount_wei, state, description, dispute_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(contract_id) DO UPDATE SET
            state=excluded.state,
            dispute_id=excluded.dispute_id,
            updated_at=CURRENT_TIMESTAMP
    """, (contract_id, buyer, seller, str(amount_wei), state, description, dispute_id))
    conn.commit()
    conn.close()


def upsert_order_partial(contract_id: int, state: str, dispute_id: int = 0) -> None:
    """Update only state and dispute_id for an existing order (preserves other columns)."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO orders (contract_id, buyer, seller, amount_wei, state, dispute_id, updated_at)
        VALUES (?, '', '', '0', ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(contract_id) DO UPDATE SET
            state=excluded.state,
            dispute_id=excluded.dispute_id,
            updated_at=CURRENT_TIMESTAMP
    """, (contract_id, state, dispute_id))
    conn.commit()
    conn.close()


def get_orders(state_filter: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    if state_filter:
        rows = conn.execute(
            "SELECT * FROM orders WHERE state=? ORDER BY contract_id DESC", (state_filter,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders ORDER BY contract_id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_order(contract_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE contract_id=?", (contract_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Disputes ──────────────────────────────────────────────────

def upsert_dispute(contract_id: int, order_id: int, reason: str = "") -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO disputes (contract_id, order_id, reason)
        VALUES (?, ?, ?)
        ON CONFLICT(contract_id) DO UPDATE SET
            reason=excluded.reason
    """, (contract_id, order_id, reason))
    conn.commit()
    conn.close()


def update_dispute_votes(contract_id: int, votes_for_buyer: int,
                         votes_for_seller: int, resolved: int = 0) -> None:
    conn = get_connection()
    conn.execute("""
        UPDATE disputes SET votes_for_buyer=?, votes_for_seller=?, resolved=?,
        resolved_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE resolved_at END
        WHERE contract_id=?
    """, (votes_for_buyer, votes_for_seller, resolved, resolved, contract_id))
    conn.commit()
    conn.close()


def get_disputes() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM disputes ORDER BY contract_id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_dispute(contract_id: int, order_id: int, reason: str) -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO disputes (contract_id, order_id, reason)
        VALUES (?, ?, ?)
    """, (contract_id, order_id, reason))
    conn.commit()
    conn.close()


# ─── Sync State ────────────────────────────────────────────────

def get_last_synced_block() -> int:
    conn = get_connection()
    row = conn.execute("SELECT value FROM sync_state WHERE key='last_block'").fetchone()
    conn.close()
    return int(row["value"]) if row else 0


def update_sync_block(block_number: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE sync_state SET value=? WHERE key='last_block'", (str(block_number),))
    conn.commit()
    conn.close()
