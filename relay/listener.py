"""
Background event listener — polls Hardhat node via web3.py, incrementally
syncs CampusEscrow on-chain events to SQLite.

Constraint 2: Daemon thread MUST NEVER CRASH. Every get_logs / event-processing
call is wrapped in try...except. On failure: log the error, sleep 5 seconds,
and continue the loop. The listener is designed to survive Hardhat node
restarts, network blips, and malformed event data.
"""
import time
import logging
from typing import Optional

from web3 import Web3
from web3.types import EventData

from relay.db import (
    upsert_order,
    upsert_order_partial,
    upsert_dispute,
    update_dispute_votes,
    get_last_synced_block,
    update_sync_block,
)

logger = logging.getLogger("relay.listener")


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


def handle_dispute_resolved(event: EventData) -> None:
    args = event.args
    update_dispute_votes(args["disputeId"], 0, 0, resolved=1)
    logger.info(f"Dispute {args['disputeId']} RESOLVED (refunded={args['refundedBuyer']})")


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
    w3: Web3,
    contract_abi: list,
    contract_address: str,
    poll_interval: float = 2.0,
) -> None:
    """
    Background daemon thread entry point.

    Constraint 2: Every network-facing operation wrapped in try...except.
    On any exception: log, sleep 5s, retry — thread never exits.
    """
    contract_addr = Web3.to_checksum_address(contract_address)
    contract = w3.eth.contract(address=contract_addr, abi=contract_abi)
    last_block = get_last_synced_block()

    logger.info(f"Listener started: block={last_block}, contract={contract_addr}")

    while True:
        try:
            current_block = w3.eth.block_number

            if current_block > last_block:
                from_block = last_block + 1
                to_block = current_block

                events_processed = 0
                for event_name, handler in EVENT_HANDLERS.items():
                    try:
                        event_obj = getattr(contract.events, event_name, None)
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
            # Constraint 2: catch-all, log, cooldown, retry
            logger.error(f"Listener error (will retry in 5s): {e}", exc_info=True)
            time.sleep(5)
