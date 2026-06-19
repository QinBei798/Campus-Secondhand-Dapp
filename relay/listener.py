"""
Background event listener — polls Geth nodes via web3.py, incrementally
syncs CampusEscrow on-chain events to SQLite.

Constraint 2: Daemon thread MUST NEVER CRASH. Every get_logs / event-processing
call is wrapped in try...except. On failure: log the error, sleep 5 seconds,
and continue the loop. The listener is designed to survive Geth node
restarts, network blips, and malformed event data.
Additionally, this listener supports RPC Failover (automatic failover to B/C if A is down).
"""
import time
import logging
from typing import Optional, List

from web3 import Web3
from web3.types import EventData
from web3.middleware import ExtraDataToPOAMiddleware

from relay.db import (
    upsert_order,
    upsert_order_partial,
    upsert_dispute,
    update_dispute_votes,
    get_last_synced_block,
    update_sync_block,
)

logger = logging.getLogger("relay.listener")

# Module-level contract ref so event handlers can query on-chain state
_escrow_contract = None


# ─── Event Handlers ────────────────────────────────────────────

def handle_order_created(event: EventData) -> None:
    args = event.args
    upsert_order(
        contract_id=args["orderId"],
        buyer=args["buyer"],
        seller=args["seller"],
        amount_wei=args["amount"],
        state="CREATED",
    )
    logger.info(f"Order {args['orderId']} CREATED: seller={args['seller']}, "
                f"buyer={args['buyer']}, amount={args['amount']}")


def handle_order_funded(event: EventData) -> None:
    args = event.args
    upsert_order_partial(contract_id=args["orderId"], state="FUNDED")
    logger.info(f"Order {args['orderId']} FUNDED by {args['buyer']}")


def handle_order_shipped(event: EventData) -> None:
    args = event.args
    upsert_order_partial(contract_id=args["orderId"], state="SHIPPED")
    logger.info(f"Order {args['orderId']} SHIPPED at {args['timestamp']}")


def handle_order_received(event: EventData) -> None:
    args = event.args
    upsert_order_partial(contract_id=args["orderId"], state="COMPLETED")
    logger.info(f"Order {args['orderId']} RECEIVED (COMPLETED) at {args['timestamp']}")


def handle_order_disputed(event: EventData) -> None:
    args = event.args
    upsert_order_partial(contract_id=args["orderId"], state="DISPUTED")
    upsert_dispute(contract_id=args["orderId"], order_id=args["orderId"], reason="")
    logger.info(f"Order {args['orderId']} DISPUTED by {args['initiator']}")


def handle_dispute_voted(event: EventData) -> None:
    args = event.args
    logger.info(f"Dispute {args['disputeId']}: arbitrator {args['arbitrator']} "
                f"voted {'for buyer' if args['forBuyer'] else 'for seller'}")
    # Fetch updated vote counts from chain
    _sync_dispute_votes(args["disputeId"])


def handle_dispute_resolved(event: EventData) -> None:
    args = event.args
    dispute_id = args["disputeId"]
    logger.info(f"Dispute {dispute_id} RESOLVED (refunded={args['refundedBuyer']})")

    # Resolve disputeId -> orderId by decoding transaction input of executeArbitration
    # This completely solves the on-chain disputeId = 0 collision bug
    order_id = None
    try:
        if _escrow_contract is not None:
            tx_hash = event.transactionHash
            tx = _escrow_contract.w3.eth.get_transaction(tx_hash)
            tx_input = tx.input.hex() if isinstance(tx.input, bytes) else tx.input
            # executeArbitration(uint256 orderId)
            # The method selector is 4 bytes (8 hex chars + 2 for "0x" = 10 chars)
            # The orderId is uint256 (32 bytes = 64 hex chars)
            order_id = int(tx_input[10:74], 16)
            logger.info(f"Successfully decoded resolved orderId={order_id} from transaction {tx_hash.hex()}")
    except Exception as e:
        logger.warning(f"Failed to decode orderId from transaction: {e}")

    # Fallback to scanning if decoding failed
    if order_id is None:
        order_id = _get_order_id_for_dispute(dispute_id)

    if order_id is not None:
        update_dispute_votes(order_id, 0, 0, resolved=1)
        upsert_order_partial(contract_id=order_id, state="COMPLETED")
    else:
        # Fallback: scan all orders on-chain to find and update the resolved one
        _refresh_all_disputed_orders()


def _get_order_id_for_dispute(dispute_id: int) -> Optional[int]:
    """Resolve on-chain disputeId -> orderId by scanning orders."""
    if _escrow_contract is None:
        return None
    try:
        count = _escrow_contract.functions.getOrderCount().call()
        for i in range(count):
            o = _escrow_contract.functions.orders(i).call()
            if o[5] == dispute_id:  # orders[i].disputeId == target
                return i
        return None
    except Exception as e:
        logger.warning(f"Failed to resolve dispute {dispute_id} -> orderId: {e}")
        return None


def _refresh_all_disputed_orders() -> None:
    """Check every DISPUTED order on-chain and sync its actual state."""
    if _escrow_contract is None:
        return
    try:
        count = _escrow_contract.functions.getOrderCount().call()
        for i in range(count):
            o = _escrow_contract.functions.orders(i).call()
            state_map = {0: 'CREATED', 1: 'FUNDED', 2: 'SHIPPED',
                         3: 'RECEIVED', 4: 'COMPLETED', 5: 'DISPUTED'}
            state = state_map.get(o[3], 'DISPUTED')
            # If order was DISPUTED but is now something else, update
            if state != 'DISPUTED':
                upsert_order_partial(contract_id=i, state=state,
                                     dispute_id=o[5])
    except Exception as e:
        logger.warning(f"Failed to refresh disputed orders: {e}")


def _sync_dispute_votes(dispute_id: int) -> None:
    """Pull latest vote counts from chain and persist to SQLite."""
    order_id = _get_order_id_for_dispute(dispute_id)
    if order_id is None:
        return
    try:
        votes = _escrow_contract.functions.getDisputeVotes(order_id).call()
        update_dispute_votes(order_id, votes[0], votes[1])
    except Exception as e:
        logger.warning(f"Failed to sync votes for dispute {dispute_id}: {e}")


EVENT_HANDLERS = {
    "OrderCreated":     handle_order_created,
    "OrderFunded":      handle_order_funded,
    "OrderShipped":     handle_order_shipped,
    "OrderReceived":    handle_order_received,
    "OrderDisputed":    handle_order_disputed,
    "DisputeVoted":     handle_dispute_voted,
    "DisputeResolved":  handle_dispute_resolved,
}


# ─── Listener Loop ─────────────────────────────────────────────

def run_event_listener(
    rpc_urls: List[str],
    contract_abi: list,
    contract_address: str,
    poll_interval: float = 2.0,
) -> None:
    """
    Background daemon thread entry point.

    Constraint 2: Every network-facing operation wrapped in try...except.
    On any exception: log, sleep 5s, retry/failover — thread never exits.
    """
    global _escrow_contract
    contract_addr = Web3.to_checksum_address(contract_address)
    
    current_rpc_idx = 0
    w3 = None
    last_block = get_last_synced_block()

    logger.info(f"Listener started: initial_block={last_block}, contract={contract_addr}")

    def connect_next_rpc() -> bool:
        nonlocal current_rpc_idx, w3
        for _ in range(len(rpc_urls)):
            url = rpc_urls[current_rpc_idx]
            try:
                temp_w3 = Web3(Web3.HTTPProvider(url))
                temp_w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if temp_w3.is_connected():
                    w3 = temp_w3
                    logger.info(f"Successfully connected to RPC node: {url}")
                    return True
            except Exception as e:
                logger.warning(f"Failed to connect to RPC node {url}: {e}")
            current_rpc_idx = (current_rpc_idx + 1) % len(rpc_urls)
        return False

    while True:
        try:
            # Reconnect/Failover if connection is lost
            if w3 is None or not w3.is_connected():
                logger.warning("No active RPC connection or connection lost. Attempting failover...")
                if not connect_next_rpc():
                    logger.error("All RPC nodes are down! Cooldown 5s...")
                    time.sleep(5)
                    continue
                _escrow_contract = w3.eth.contract(address=contract_addr, abi=contract_abi)
                # Re-sync last_block in case DB changed
                last_block = get_last_synced_block()

            current_block = w3.eth.block_number

            if current_block > last_block:
                from_block = last_block + 1
                to_block = current_block

                events_processed = 0
                for event_name, handler in EVENT_HANDLERS.items():
                    try:
                        event_obj = getattr(_escrow_contract.events, event_name, None)
                        if event_obj is None:
                            continue
                        logs = event_obj.get_logs(from_block=from_block, to_block=to_block)
                        for log in logs:
                            handler(log)
                            events_processed += 1
                    except Exception as inner_e:
                        logger.warning(f"Failed to process {event_name} events: {inner_e}")

                if events_processed > 0:
                    logger.info(f"Synced {events_processed} events from blocks "
                                f"{from_block}-{to_block}")

                update_sync_block(current_block)
                last_block = current_block

            time.sleep(poll_interval)

        except Exception as e:
            # Cooldown, log, set w3 to None to trigger failover on next loop
            logger.error(f"Listener error (will retry/failover in 5s): {e}", exc_info=True)
            w3 = None
            time.sleep(5)
