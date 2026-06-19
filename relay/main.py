"""
FastAPI off-chain relay — REST API + optional background event listener.

Constraint 3: Merkle proof lookup imports scripts/merkle_gen.py as a Python
module (via sys.path). ZERO subprocess calls — function invocation only.
"""
import json
import os
import sys
import logging
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Constraint 3: import merkle_gen as module (NOT subprocess)
_scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
import merkle_gen  # noqa: E402

from relay.db import init_db, get_orders, get_order, get_disputes, create_dispute  # noqa: E402
from relay.models import (  # noqa: E402
    OrderResponse, DisputeResponse, DisputeCreate, WhitelistProofResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("relay.main")

# ─── Merkle whitelist cache ────────────────────────────────────

_WHITELIST_CACHE: Optional[dict] = None


def _get_whitelist() -> dict:
    """Lazy-load Merkle whitelist via direct module import (Constraint 3)."""
    global _WHITELIST_CACHE
    if _WHITELIST_CACHE is None:
        addresses = [
            "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
            "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
            "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
            "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
            "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
            "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f",
            "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720",
        ]
        _WHITELIST_CACHE = merkle_gen.generate_whitelist(addresses, nonce=0)
    return _WHITELIST_CACHE


# ─── Config loader ────────────────────────────────────────────────

def _load_deploy_config() -> dict:
    deploy_path = os.path.join(os.path.dirname(__file__), "deploy.json")
    if os.path.exists(deploy_path):
        with open(deploy_path) as f:
            return json.load(f)
    return {}


# ─── Lifespan ──────────────────────────────────────────────────

RPC_ENDPOINTS = [
    "http://127.0.0.1:8545",  # Node A
    "http://127.0.0.1:8547",  # Node B
    "http://127.0.0.1:8549"   # Node C
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
    import sqlite3

    # Find first working RPC for startup check
    w3 = None
    for url in RPC_ENDPOINTS:
        try:
            temp_w3 = Web3(Web3.HTTPProvider(url))
            temp_w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if temp_w3.is_connected():
                w3 = temp_w3
                break
        except Exception:
            pass

    deploy_cfg = _load_deploy_config()

    # Auto-detect chain reset: if last synced block > current chain block, clear stale cache
    init_db()
    if w3 and w3.is_connected():
        from relay.db import get_last_synced_block
        last_synced = get_last_synced_block()
        current_block = w3.eth.block_number
        if last_synced > current_block:
            logger.warning(f"Chain reset detected (DB={last_synced}, chain={current_block}). "
                           f"Purging stale cache.")
            db_path = os.path.join(os.path.dirname(__file__), "relay.db")
            conn = sqlite3.connect(db_path)
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM disputes")
            conn.execute("DELETE FROM sync_state")  # Fixed typo (meta -> sync_state)
            conn.commit()
            conn.close()
            init_db()

    contract_addr = os.environ.get("CONTRACT_ADDR", deploy_cfg.get("campus_escrow", ""))

    if contract_addr:
        from relay.listener import run_event_listener

        _artifacts = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "artifacts", "contracts", "CampusEscrow.sol", "CampusEscrow.json",
        )
        with open(_artifacts) as f:
            escrow_artifact = json.load(f)

        t = threading.Thread(
            target=run_event_listener,
            args=(RPC_ENDPOINTS, escrow_artifact["abi"], contract_addr),
            daemon=True,
            name="event-listener",
        )
        t.start()
        logger.info(f"Event listener started for {contract_addr}")

    yield
    logger.info("Relay shutdown complete")


# ─── FastAPI App ───────────────────────────────────────────────

app = FastAPI(
    title="Campus Secondhand Relay",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    """Return deploy.json contents so frontend doesn't hardcode addresses."""
    cfg = _load_deploy_config()
    if not cfg:
        raise HTTPException(status_code=503, detail="Not deployed — run relay/deploy.py first")
    return cfg


# ─── Orders ────────────────────────────────────────────────────

@app.get("/api/orders", response_model=list[OrderResponse])
async def list_orders(state: Optional[str] = Query(None)):
    orders = get_orders(state_filter=state)
    return [OrderResponse(**o) for o in orders]


@app.get("/api/orders/{contract_id}", response_model=OrderResponse)
async def get_order_by_id(contract_id: int):
    order = get_order(contract_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse(**order)


# ─── Disputes ──────────────────────────────────────────────────

@app.get("/api/disputes", response_model=list[DisputeResponse])
async def list_disputes():
    disputes = get_disputes()
    return [DisputeResponse(**d) for d in disputes]


@app.post("/api/disputes", status_code=201, response_model=DisputeResponse)
async def create_dispute_endpoint(body: DisputeCreate):
    # Determine next contract_id from existing disputes count
    existing = get_disputes()
    next_contract_id = len(existing)
    create_dispute(contract_id=next_contract_id, order_id=body.order_id, reason=body.reason)
    disputes = get_disputes()
    return DisputeResponse(**disputes[-1])


# ─── Whitelist ─────────────────────────────────────────────────

@app.get("/api/whitelist/proof/{address}", response_model=WhitelistProofResponse)
async def get_whitelist_proof(address: str):
    """
    Constraint 3: Direct Python module import of merkle_gen.
    Looks up Merkle proof for a given Ethereum address.
    """
    wl = _get_whitelist()
    address_lower = address.lower()
    for entry in wl["entries"]:
        if entry["address"].lower() == address_lower:
            return WhitelistProofResponse(
                address=address,
                leaf=entry["leaf"],
                proof=entry["proof"],
                root=wl["root"],
            )
    raise HTTPException(status_code=404, detail="Address not in whitelist")
