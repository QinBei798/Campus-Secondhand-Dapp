// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * MerkleWhitelist — 白名单准入合约
 *
 * 核心算法迁移自 mybitcoin/src/Core/Merkle.cpp:
 *   两两归约 + 奇数尾节点自复制 → keccak256 等价 Hash256
 *
 * 与 OpenZeppelin MerkleProof 保持值排序拼接策略，确保
 * scripts/merkle_gen.py 预计算的 proof 可被合约正确验证
 */
contract MerkleWhitelist {
    bytes32 public merkleRoot;
    address public owner;
    mapping(bytes32 => bool) public usedLeafs;

    event RootUpdated(bytes32 oldRoot, bytes32 newRoot);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function setMerkleRoot(bytes32 _root) external onlyOwner {
        bytes32 oldRoot = merkleRoot;
        merkleRoot = _root;
        emit RootUpdated(oldRoot, _root);
    }

    /**
     * 验证 Merkle Proof
     *
     * 对标 Merkle.cpp:13-28 的 while-loop 归约逻辑:
     *   computedHash = leaf
     *   while (proof 未耗尽):
     *       两两排序拼接 → keccak256 (等价 Hash256)
     *   return computedHash == merkleRoot
     *
     * @return true 当 proof 有效; revert 当 proof 无效
     */
    function verify(bytes32[] calldata proof, bytes32 leaf) public view returns (bool) {
        bytes32 computed = leaf;

        for (uint256 i = 0; i < proof.length; i++) {
            // 值排序拼接 — 与 scripts/merkle_gen.py 中的排序逻辑一致
            if (computed < proof[i]) {
                computed = keccak256(abi.encodePacked(computed, proof[i]));
            } else {
                computed = keccak256(abi.encodePacked(proof[i], computed));
            }
        }

        require(computed == merkleRoot, "Invalid proof");
        return true;
    }

    /**
     * 验证并消费叶子 (防重放)
     *
     * 对比 Merkle.cpp:31 — 只返回 root，不防重放
     * 本合约在此基础上增加 usedLeafs mapping 防重放攻击
     */
    function verifyAndConsume(bytes32[] calldata proof, bytes32 leaf) external {
        require(!usedLeafs[leaf], "Leaf already used");
        verify(proof, leaf); // will revert if invalid
        usedLeafs[leaf] = true;
    }

    /**
     * 查询叶子是否已被消费
     */
    function isLeafUsed(bytes32 leaf) external view returns (bool) {
        return usedLeafs[leaf];
    }
}
