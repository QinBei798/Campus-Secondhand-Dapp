"""Pydantic request/response models for the relay FastAPI app."""
from pydantic import BaseModel
from typing import Optional, List


class OrderResponse(BaseModel):
    contract_id: int
    buyer: str
    seller: str
    amount_wei: str
    state: str
    description: str = ""
    dispute_id: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DisputeResponse(BaseModel):
    contract_id: int
    order_id: int
    reason: str = ""
    votes_for_buyer: int = 0
    votes_for_seller: int = 0
    resolved: int = 0
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None


class DisputeCreate(BaseModel):
    order_id: int
    reason: str


class WhitelistProofResponse(BaseModel):
    address: str
    leaf: str
    proof: List[str]
    root: str
