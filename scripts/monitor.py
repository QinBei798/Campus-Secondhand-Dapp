#!/usr/bin/env python3
"""
Geth Multi-Node Consortium Network Monitor

A real-time terminal visualizer that connects to the 3 Geth nodes in the private 
network, displays their heights, visualizes how blocks are created and linked together
using Parent Hashes, and shows transactions getting packaged onto blocks.

Usage:
    python3 scripts/monitor.py
"""

import os
import sys
import time
import json
import urllib.request

RPC_NODES = {
    "Node A": "http://127.0.0.1:8545",
    "Node B": "http://127.0.0.1:8547",
    "Node C": "http://127.0.0.1:8549"
}

SEALER_NAMES = {
    "0x347494f66e8093f7cffcc8519db75640a28dcaef": "Node A",
    "0x29a1e3c84bbcb19fd5afb0b6c421bdb28c918304": "Node B",
    "0x7a20e97c14e215ad7188ac412cb638f252773637": "Node C"
}

def json_rpc(url, method, params=[]):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=1) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None

def get_node_status():
    status = {}
    for name, url in RPC_NODES.items():
        res_height = json_rpc(url, "eth_blockNumber")
        res_peers = json_rpc(url, "net_peerCount")
        
        if res_height and "result" in res_height:
            height = int(res_height["result"], 16)
        else:
            height = "Offline"
            
        if res_peers and "result" in res_peers:
            peers = int(res_peers["result"], 16)
        else:
            peers = 0
            
        status[name] = {"height": height, "peers": peers, "url": url}
    return status

def get_sealer_name(miner_addr):
    if not miner_addr:
        return "Unknown"
    addr_lower = miner_addr.lower()
    return SEALER_NAMES.get(addr_lower, miner_addr[:10] + "...")

def format_hash(h):
    if not h:
        return "None"
    return f"{h[:6]}...{h[-4:]}"

def get_recent_blocks(status, limit=8):
    # Find a working node to query blocks
    active_node_url = None
    for name, info in status.items():
        if info["height"] != "Offline":
            active_node_url = info["url"]
            max_height = info["height"]
            break
            
    if not active_node_url:
        return [], []

    blocks = []
    txs = []
    
    start_block = max(0, max_height - limit + 1)
    for h in range(max_height, start_block - 1, -1):
        hex_h = hex(h)
        res_block = json_rpc(active_node_url, "eth_getBlockByNumber", [hex_h, True])
        if res_block and "result" in res_block and res_block["result"]:
            b = res_block["result"]
            block_data = {
                "number": int(b["number"], 16),
                "hash": b["hash"],
                "parent_hash": b["parentHash"],
                "miner": b["miner"],
                "timestamp": int(b["timestamp"], 16),
                "tx_count": len(b["transactions"]),
                "sealer": get_sealer_name(b["miner"])
            }
            blocks.append(block_data)
            
            # Extract transactions
            for tx in b["transactions"]:
                tx_data = {
                    "hash": tx["hash"],
                    "block": block_data["number"],
                    "from": tx["from"],
                    "to": tx.get("to") or "Contract Deployment",
                    "value": int(tx.get("value", "0x0"), 16) / 1e18
                }
                txs.append(tx_data)
                
    return blocks, txs

def clear_screen():
    os.system('clear' if os.name != 'nt' else 'cls')

def main():
    print("Initializing Consortium Network Monitor...")
    time.sleep(1)
    
    seen_txs = []
    seen_tx_hashes = set()
    
    try:
        while True:
            status = get_node_status()
            blocks, latest_txs = get_recent_blocks(status)
            
            # Add any new transactions to our persistent history
            for tx in latest_txs:
                if tx["hash"] not in seen_tx_hashes:
                    seen_tx_hashes.add(tx["hash"])
                    seen_txs.append(tx)
            
            # Sort seen_txs by block number descending so newest is at the top
            seen_txs.sort(key=lambda x: x["block"], reverse=True)
            
            # Limit persistent history to last 15 unique transactions to avoid screen overflow
            if len(seen_txs) > 15:
                for old_tx in seen_txs[15:]:
                    seen_tx_hashes.discard(old_tx["hash"])
                seen_txs = seen_txs[:15]
            
            clear_screen()
            print("=" * 80)
            print("                 GETH POA MULTI-NODE CONSORTIUM CHAIN MONITOR")
            print("=" * 80)
            print()
            
            # 1. Print Node status and block heights
            print("[1] Node Status & Synchronization Heights")
            print("-" * 80)
            all_offline = True
            for name, info in status.items():
                if info["height"] == "Offline":
                    status_str = "\033[91mOFFLINE\033[0m"
                else:
                    status_str = f"\033[92mONLINE\033[0m (Block Height: {info['height']})"
                    all_offline = False
                print(f"  * {name:<8}: {status_str:<40} | Active Peers: {info['peers']}")
            print("-" * 80)
            print()
            
            if all_offline:
                print("  \033[91m[Error] All Geth nodes are offline. Please run ./start.sh first!\033[0m")
                time.sleep(3)
                continue
                
            # 2. Print block chain link visualization
            print("[2] Blockchain Structure & Link Visualization (Chain Link)")
            print("-" * 80)
            
            if not blocks:
                print("  No blocks retrieved yet.")
            else:
                for idx, b in enumerate(blocks):
                    # Highlight if block contains transactions
                    tx_flag = ""
                    if b["tx_count"] > 0:
                        tx_flag = f" <=== \033[93m★ PACKAGED {b['tx_count']} TX(s) ★\033[0m"
                        
                    print(f"  [ Block #{b['number']:<5} ] ── Hash: {format_hash(b['hash'])}")
                    print(f"               ├── Sealer: {b['sealer']} (Miner: {format_hash(b['miner'])})")
                    print(f"               └── Tx Count: {b['tx_count']}{tx_flag}")
                    
                    if idx < len(blocks) - 1:
                        print("                     │")
                        print(f"                     ▼ (ParentHash: {format_hash(b['parent_hash'])})")
            print("-" * 80)
            print()
            
            # 3. Print packaged transactions
            print("[3] Persistent Transaction History (Last 15 Unique Transactions)")
            print("-" * 80)
            if not seen_txs:
                print("  No transactions detected yet (waiting for actions in DApp...)")
            else:
                for tx in seen_txs:
                    to_str = get_sealer_name(tx["to"]) if tx["to"] else "Deployment"
                    if len(to_str) > 15:
                        to_str = format_hash(tx["to"])
                    from_str = format_hash(tx["from"])
                    
                    print(f"  * Tx: {format_hash(tx['hash'])} | Block: #{tx['block']} | "
                          f"From: {from_str} ──→ To: {to_str} | Value: {tx['value']:.4f} ETH")
            print("-" * 80)
            print("\nPress Ctrl+C to exit monitor. Making transactions in DApp will show up here!")
            
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
