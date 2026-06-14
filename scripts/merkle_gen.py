#!/usr/bin/env python3
"""
Merkle Tree Generator — 迁移自 mybitcoin/src/Core/Merkle.cpp

算法核心：
  1. 将输入列表哈希为固定长度叶子层
  2. 两层循环：while len(hashes) > 1 → 奇数尾节点自复制 → 两两 concat + keccak256
  3. 返回 Merkle Root + 每个叶子的 Proof (路径哈希数组)

对标 Merkle.cpp:
  - ComputeMerkleRoot()           → compute_merkle_root()
  - 奇数尾复制 (hashes.push_back(hashes.back())) → 第 52 行
  - 两两归约 (concat left+right → Hash256)       → 第 53-57 行
"""

import json
import sys
from typing import List, Tuple
from web3 import Web3

w3 = Web3()


def keccak256(data: bytes) -> bytes:
    """等价于 Solidity keccak256(abi.encodePacked(...))"""
    return w3.keccak(data)


def build_leaf(address: str, nonce: int) -> bytes:
    """
    构造叶子节点
    等价于 Solidity: keccak256(abi.encodePacked(address, nonce))
    """
    encoded = w3.codec.encode(["address", "uint256"], [address, nonce])
    return keccak256(encoded)


def compute_merkle_root(leaves: List[bytes]) -> bytes:
    """
    对标 Merkle.cpp::ComputeMerkleRoot()

    输入: 已哈希过的叶子列表 (每片叶子已是 32 字节 keccak256)
    输出: 单一 32 字节 Merkle Root

    算法步骤 (逐行对应 Merkle.cpp:12-32):
    """
    if not leaves:
        return b"\x00" * 32

    hashes = leaves[:]  # ← Merkle.cpp:8-10: 拷贝交易 ID 列表

    # ← Merkle.cpp:13: while (hashes.size() > 1)
    while len(hashes) > 1:
        # ← Merkle.cpp:15-17: 奇数尾节点自复制
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])

        new_level = []
        # ← Merkle.cpp:21: for (size_t i = 0; i < hashes.size(); i += 2)
        for i in range(0, len(hashes), 2):
            left = hashes[i]
            right = hashes[i + 1]
            # 值排序拼接 — 对标 OpenZeppelin MerkleProof (与 Solidity 合约一致)
            if left < right:
                concat = left + right
            else:
                concat = right + left
            # ← Merkle.cpp:26: Hash256(concat) → 等价 keccak256
            new_level.append(keccak256(concat))

        hashes = new_level  # ← Merkle.cpp:28

    # ← Merkle.cpp:31: return hashes[0]
    return hashes[0]


def generate_proof(leaves: List[bytes], leaf_index: int) -> List[bytes]:
    """
    为指定索引的叶子生成 Merkle Proof (同级路径哈希数组)

    对标 Solidity 的 verify(bytes32[] proof, bytes32 leaf) 验证逻辑:
      computedHash = leaf
      for each proofElement in proof:
          if computedHash < proofElement:
              computedHash = keccak256(computedHash || proofElement)
          else:
              computedHash = keccak256(proofElement || computedHash)
      return computedHash == merkleRoot
    """
    if leaf_index < 0 or leaf_index >= len(leaves):
        raise IndexError(f"Leaf index {leaf_index} out of range [0, {len(leaves)})")

    hashes = leaves[:]
    proof = []
    target_idx = leaf_index

    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])

        new_level = []
        for i in range(0, len(hashes), 2):
            left = hashes[i]
            right = hashes[i + 1]
            # 值排序拼接 — 与 compute_merkle_root 保持一致
            if left < right:
                parent = keccak256(left + right)
            else:
                parent = keccak256(right + left)
            new_level.append(parent)

            # 记录证明：目标索引对应的同级哈希
            if i == target_idx:
                # 目标在左，证明在右
                proof.append(hashes[i + 1])
            elif i + 1 == target_idx:
                # 目标在右，证明在左
                proof.append(hashes[i])

        hashes = new_level
        target_idx //= 2  # 父节点在下一层的新索引

    return proof


def verify_proof(proof: List[bytes], leaf: bytes, root: bytes) -> bool:
    """
    验证 Merkle Proof (与 Solidity 合约 verify() 一致)
    """
    computed = leaf
    for p in proof:
        if computed < p:
            computed = keccak256(computed + p)
        else:
            computed = keccak256(p + computed)
    return computed == root


def generate_whitelist(addresses: List[str], nonce: int = 0) -> dict:
    """
    完整白名单生成流程

    输入:
      addresses: Hardhat 测试地址列表 (Signers)
      nonce: 可选的有效期标记 (timestamp)

    输出:
      {
        "root": "0x...",       # 32 字节 Merkle Root
        "nonce": 1234567890,
        "entries": [
          {"address": "0x...", "proof": ["0x...", ...]},
          ...
        ]
      }
    """
    # 步骤 1: 构建叶子层
    leaves = []
    for addr in addresses:
        leaf = build_leaf(addr, nonce)
        leaves.append(leaf)

    # 步骤 2: 计算 Merkle Root (对标 Merkle.cpp)
    root = compute_merkle_root(leaves)

    # 步骤 3: 为每个地址生成 proof
    entries = []
    for i, addr in enumerate(addresses):
        proof = generate_proof(leaves, i)
        entries.append({
            "address": addr,
            "leaf": "0x" + leaves[i].hex(),
            "proof": ["0x" + p.hex() for p in proof],
        })

    return {
        "root": "0x" + root.hex(),
        "nonce": nonce,
        "entries": entries,
    }


# ─── CLI 入口 ─────────────────────────────────────────────────
if __name__ == "__main__":
    # 测试地址 (模拟 Hardhat 本地链 10 个 Signers)
    test_addresses = [
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

    # 支持自定义 nonce (如: python merkle_gen.py 1718352000)
    nonce = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    result = generate_whitelist(test_addresses, nonce)

    # 输出 JSON
    print(json.dumps(result, indent=2))

    # 自检: 验证所有 proof 均通过
    root_bytes = bytes.fromhex(result["root"][2:])
    all_ok = True
    for entry in result["entries"]:
        leaf_bytes = bytes.fromhex(entry["leaf"][2:])
        proof_bytes = [bytes.fromhex(p[2:]) for p in entry["proof"]]
        if not verify_proof(proof_bytes, leaf_bytes, root_bytes):
            print(f"\n[FAIL] Proof verification failed for {entry['address']}", file=sys.stderr)
            all_ok = False

    if all_ok:
        print(f"\n[OK] All {len(result['entries'])} proofs verified against root {result['root']}", file=sys.stderr)
