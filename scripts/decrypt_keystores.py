import os
import json
from eth_account import Account

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PN_DIR = os.path.join(ROOT_DIR, "private-network")
PW_FILE = os.path.join(PN_DIR, "password.txt")

with open(PW_FILE, "r") as f:
    password = f.read().strip()

nodes = ["nodeA", "nodeB", "nodeC"]

for node in nodes:
    keystore_dir = os.path.join(PN_DIR, node, "keystore")
    if not os.path.exists(keystore_dir):
        print(f"{node}: No keystore directory found.")
        continue
    
    files = os.listdir(keystore_dir)
    for file in files:
        if file.startswith("UTC--"):
            file_path = os.path.join(keystore_dir, file)
            with open(file_path, "r") as f:
                keystore_data = json.load(f)
            try:
                private_key = Account.decrypt(keystore_data, password).hex()
                address = Account.from_key(private_key).address
                print(f"{node} ({address}): {private_key}")
            except Exception as e:
                print(f"{node}: Failed to decrypt keystore {file}: {e}")
