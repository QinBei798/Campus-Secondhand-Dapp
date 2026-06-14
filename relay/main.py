"""
FastAPI off-chain relay — REST API + optional background event listener.

Constraint 3: Merkle proof lookup imports scripts/merkle_gen.py as a Python
module (via sys.path). ZERO subprocess calls — function invocation only.
"""
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


# ─── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    contract_addr = os.environ.get("CONTRACT_ADDR", "")

    if contract_addr:
        from web3 import Web3
        from relay.listener import run_event_listener

        hardhat_url = os.environ.get("HARDHAT_URL", "http://127.0.0.1:8545")
        w3 = Web3(Web3.HTTPProvider(hardhat_url))

        if w3.is_connected():
            # Load ABI from Hardhat artifacts
            _artifacts = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "artifacts", "contracts", "CampusEscrow.sol", "CampusEscrow.json",
            )
            import json
            with open(_artifacts) as f:
                escrow_artifact = json.load(f)

            t = threading.Thread(
                target=run_event_listener,
                args=(w3, escrow_artifact["abi"], contract_addr),
                daemon=True,
                name="event-listener",
            )
            t.start()
            logger.info(f"Event listener started for {contract_addr}")
        else:
            logger.warning(f"Hardhat node unreachable at {hardhat_url}")

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
