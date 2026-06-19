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
    from web3.middleware import ExtraDataToPOAMiddleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to Geth node at {hardhat_url}")
        sys.exit(1)

    deployer = w3.eth.accounts[0] # Node A (unlocked)
    arbitrators = [
        Web3.to_checksum_address("0x347494f66e8093f7cffcc8519db75640a28dcaef"), # Node A
        Web3.to_checksum_address("0x29a1e3c84bbcb19fd5afb0b6c421bdb28c918304"), # Node B
        Web3.to_checksum_address("0x7a20e97c14e215ad7188ac412cb638f252773637")  # Node C
    ]

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
    whitelist_addresses = [
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
    wl = merkle_gen.generate_whitelist(whitelist_addresses, nonce=0)
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
    parser = argparse.ArgumentParser(description="Deploy contracts to Hardhat node")
    parser.add_argument("--hardhat-url", default="http://127.0.0.1:8545",
                        help="Hardhat node RPC URL")
    args = parser.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.hardhat_url))
    from web3.middleware import ExtraDataToPOAMiddleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    deploy_json_path = os.path.join(os.path.dirname(__file__), "deploy.json")
    db_path = os.path.join(os.path.dirname(__file__), "relay.db")

    reused = False
    if w3.is_connected() and os.path.exists(deploy_json_path):
        try:
            with open(deploy_json_path) as f:
                deploy_info = json.load(f)
            escrow_addr = deploy_info.get("campus_escrow")
            wl_addr = deploy_info.get("merkle_whitelist")

            if escrow_addr and wl_addr:
                escrow_code = w3.eth.get_code(Web3.to_checksum_address(escrow_addr))
                wl_code = w3.eth.get_code(Web3.to_checksum_address(wl_addr))

                if escrow_code and len(escrow_code) > 0 and wl_code and len(wl_code) > 0:
                    print(f"Detected active contracts already deployed on persistent chain:")
                    print(f"  MerkleWhitelist: {wl_addr}")
                    print(f"  CampusEscrow:    {escrow_addr}")
                    print("Skipping contract re-deployment to preserve transaction history.")
                    reused = True
        except Exception as e:
            print(f"Note: Failed to check existing deployment ({e}). Proceeding with clean deploy.")

    if not reused:
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Cleared stale relay.db")
        deploy(args.hardhat_url)
