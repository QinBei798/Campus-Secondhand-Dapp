"""
Deploy MerkleWhitelist + CampusEscrow to local Hardhat node via web3.py.

Usage:
    python relay/deploy.py [--hardhat-url http://127.0.0.1:8545]

Outputs deploy.json with contract addresses + Merkle root for relay/frontend.
"""
import json
import os
import sys
import argparse
from web3 import Web3

# Constraint 3: import merkle_gen as module
_scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, _scripts_dir)
import merkle_gen


def load_artifact(name: str) -> dict:
    artifacts_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "artifacts", "contracts", f"{name}.sol", f"{name}.json",
    )
    with open(artifacts_dir) as f:
        return json.load(f)


def deploy(hardhat_url: str = "http://127.0.0.1:8545") -> dict:
    w3 = Web3(Web3.HTTPProvider(hardhat_url))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to Hardhat node at {hardhat_url}")
        print("Start it with: npx hardhat node")
        sys.exit(1)

    deployer = w3.eth.accounts[0]
    arbitrators = w3.eth.accounts[3:6]

    print(f"Chain ID: {w3.eth.chain_id}")
    print(f"Deployer:  {deployer}")
    print(f"Balance:   {w3.from_wei(w3.eth.get_balance(deployer), 'ether')} ETH")
    print(f"Arbitrators: {arbitrators}")

    # ─── 1. Deploy MerkleWhitelist ─────────────────────────────
    wl_artifact = load_artifact("MerkleWhitelist")
    Whitelist = w3.eth.contract(abi=wl_artifact["abi"], bytecode=wl_artifact["bytecode"])
    tx_hash = Whitelist.constructor().transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    whitelist_addr = receipt.contractAddress
    print(f"\n[1/2] MerkleWhitelist: {whitelist_addr}  (gas: {receipt.gasUsed})")

    # ─── 2. Set Merkle root ────────────────────────────────────
    wl = merkle_gen.generate_whitelist(w3.eth.accounts[:10], nonce=0)
    merkle_root_hex = wl["root"]
    wl_contract = w3.eth.contract(address=whitelist_addr, abi=wl_artifact["abi"])
    tx_hash = wl_contract.functions.setMerkleRoot(
        bytes.fromhex(merkle_root_hex[2:])
    ).transact({"from": deployer})
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"     Merkle root: {merkle_root_hex}")

    # ─── 3. Deploy CampusEscrow ────────────────────────────────
    escrow_artifact = load_artifact("CampusEscrow")
    Escrow = w3.eth.contract(abi=escrow_artifact["abi"], bytecode=escrow_artifact["bytecode"])
    tx_hash = Escrow.constructor(whitelist_addr, arbitrators).transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    escrow_addr = receipt.contractAddress
    print(f"\n[2/2] CampusEscrow:    {escrow_addr}  (gas: {receipt.gasUsed})")

    # ─── 4. Save deployment info ───────────────────────────────
    out = {
        "chain_id": w3.eth.chain_id,
        "merkle_whitelist": whitelist_addr,
        "campus_escrow": escrow_addr,
        "arbitrators": arbitrators,
        "merkle_root": merkle_root_hex,
    }
    out_path = os.path.join(os.path.dirname(__file__), "deploy.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nDeploy info saved to {out_path}")
    print(f"Start relay:  CONTRACT_ADDR={escrow_addr} uvicorn relay.main:app --reload")
    return out


if __name__ == "__main__":
    # Nuke stale SQLite cache so relay starts fresh on re-deploy
    db_path = os.path.join(os.path.dirname(__file__), "relay.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Cleared stale relay.db")

    parser = argparse.ArgumentParser(description="Deploy contracts to Hardhat node")
    parser.add_argument("--hardhat-url", default="http://127.0.0.1:8545",
                        help="Hardhat node RPC URL")
    args = parser.parse_args()
    deploy(args.hardhat_url)
