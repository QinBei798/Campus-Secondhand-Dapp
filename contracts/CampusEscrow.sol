// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./MerkleWhitelist.sol";

/**
 * CampusEscrow — 基于区块链的校园二手交易担保托管
 *
 * 设计范式借鉴 mybitcoin/src/Core/Blockchain.cpp:98-173:
 *   影子副本原子提交 (Deep Copy → Validate → Commit)
 *   所有状态变更先在 memory 副本验证，通过后方可写入 storage
 *
 * 状态机:
 *   CREATED → FUNDED → SHIPPED → RECEIVED → COMPLETED
 *                ↓                           ↑
 *             DISPUTED ──────────────────────↗ (via 2/3 multisig)
 */
contract CampusEscrow {
    using {addressBytesLt} for bytes32;

    MerkleWhitelist public whitelist;

    enum State { CREATED, FUNDED, SHIPPED, RECEIVED, COMPLETED, DISPUTED }

    struct Order {
        address buyer;
        address seller;
        uint256 amount;
        State state;
        string description;
        uint256 disputeId;
    }

    struct Dispute {
        uint256 orderId;
        string reason;
        uint256 votesForBuyer;
        uint256 votesForSeller;
        mapping(address => bool) hasVoted;
        bool resolved;
    }

    // ─── Storage ──────────────────────────────────────────────────
    Order[] public orders;
    Dispute[] private disputes;
    address[] public arbitrators;
    mapping(address => bool) public isWhitelisted;       // 已注册白名单地址
    mapping(address => bool) public isArbitrator;

    uint256 public constant ARBITRATOR_COUNT = 3;
    uint256 public constant VOTE_THRESHOLD = 2;

    // ─── Events ───────────────────────────────────────────────────
    event OrderCreated(uint256 indexed orderId, address seller, address buyer, uint256 amount);
    event OrderFunded(uint256 indexed orderId, address buyer, uint256 amount);
    event OrderShipped(uint256 indexed orderId, uint256 timestamp);
    event OrderReceived(uint256 indexed orderId, uint256 timestamp);
    event OrderDisputed(uint256 indexed orderId, address initiator);
    event DisputeVoted(uint256 indexed disputeId, address arbitrator, bool forBuyer);
    event DisputeResolved(uint256 indexed disputeId, bool refundedBuyer);
    event WhitelistRegistered(address indexed user);

    // ─── Modifiers ────────────────────────────────────────────────
    modifier onlyArbitrator() {
        require(isArbitrator[msg.sender], "Only arbitrator can vote");
        _;
    }

    modifier onlyBuyer(uint256 orderId) {
        // 影子验证: 从 storage 读取订单到 memory，在 memory 上做权限检查
        Order memory shadow = orders[orderId];
        require(shadow.buyer == msg.sender, "Only buyer");
        _;
    }

    modifier onlySeller(uint256 orderId) {
        Order memory shadow = orders[orderId];
        require(shadow.seller == msg.sender, "Only seller");
        _;
    }

    modifier onlyInState(uint256 orderId, State required) {
        Order memory shadow = orders[orderId];
        require(shadow.state == required, "Invalid state transition");
        _;
    }

    // ─── Constructor ──────────────────────────────────────────────
    constructor(address _whitelist, address[] memory _arbitrators) {
        require(_arbitrators.length == ARBITRATOR_COUNT, "Need exactly 3 arbitrators");
        whitelist = MerkleWhitelist(_whitelist);
        arbitrators = _arbitrators;
        for (uint256 i = 0; i < _arbitrators.length; i++) {
            require(_arbitrators[i] != address(0), "Invalid arbitrator address");
            isArbitrator[_arbitrators[i]] = true;
        }
    }

    // ─── Whitelist ────────────────────────────────────────────────
    /**
     * 用户注册白名单身份
     * 内部调用 MerkleWhitelist.verifyAndConsume() 验证 proof
     *
     * @param proof Merkle Proof 数组 (由 scripts/merkle_gen.py 生成)
     */
    function registerWhitelist(bytes32[] calldata proof) external {
        bytes32 leaf = keccak256(abi.encode(msg.sender, uint256(0)));
        whitelist.verifyAndConsume(proof, leaf);
        isWhitelisted[msg.sender] = true;
        emit WhitelistRegistered(msg.sender);
    }

    // ─── 核心业务流程 ─────────────────────────────────────────────

    /**
     * 卖家创建订单 (挂牌)
     *
     * [影子验证] 检查 msg.sender 是否已注册白名单
     */
    function createOrder(address _buyer, uint256 _price, string calldata _description)
        external
        returns (uint256 orderId)
    {
        // 影子状态: 读取白名单状态到 memory
        bool shadowWhitelist = isWhitelisted[msg.sender];
        require(shadowWhitelist, "Not whitelisted");

        require(_buyer != address(0), "Invalid buyer");
        require(_buyer != msg.sender, "Cannot buy from self");
        require(_price > 0, "Price must be positive");

        orderId = orders.length;
        orders.push(Order({
            buyer: _buyer,
            seller: msg.sender,
            amount: _price,
            state: State.CREATED,
            description: _description,
            disputeId: 0
        }));

        emit OrderCreated(orderId, msg.sender, _buyer, _price);
    }

    /**
     * 买家付款 (资金硬锁定)
     *
     * [影子验证] 确认 msg.sender == buyer AND 当前状态 == CREATED AND msg.value >= price
     * 验证全部通过后原子写入 storage
     */
    function fundOrder(uint256 orderId)
        external
        payable
        onlyInState(orderId, State.CREATED)
        onlyBuyer(orderId)
    {
        Order memory shadow = orders[orderId];
        require(msg.value >= shadow.amount, "Insufficient payment");

        // 原子提交: 所有验证通过，写入 storage
        orders[orderId].state = State.FUNDED;

        emit OrderFunded(orderId, msg.sender, msg.value);
    }

    /**
     * 卖家发货
     */
    function shipOrder(uint256 orderId)
        external
        onlyInState(orderId, State.FUNDED)
        onlySeller(orderId)
    {
        orders[orderId].state = State.SHIPPED;

        emit OrderShipped(orderId, block.timestamp);
    }

    /**
     * 买家确认收货 → 自动释放资金给卖家
     */
    function receiveOrder(uint256 orderId)
        external
        onlyInState(orderId, State.SHIPPED)
        onlyBuyer(orderId)
    {
        Order memory shadow = orders[orderId];

        // 影子验证 → 原子提交
        orders[orderId].state = State.COMPLETED;

        // 释放资金给卖家 (CEI: Checks-Effects-Interactions)
        (bool sent, ) = payable(shadow.seller).call{value: shadow.amount}("");
        require(sent, "Transfer to seller failed");

        emit OrderReceived(orderId, block.timestamp);
    }

    // ─── 争议仲裁路径 ─────────────────────────────────────────────

    /**
     * 买方发起争议申诉
     *
     * 允许从 FUNDED (付款后卖家不发货) 或 SHIPPED (收货后发现货不对板) 发起争议
     * 状态原子变更为 DISPUTED，创建新的 Dispute 记录
     */
    function raiseDispute(uint256 orderId, string calldata reason)
        external
        onlyBuyer(orderId)
    {
        Order memory shadow = orders[orderId];
        require(
            shadow.state == State.FUNDED || shadow.state == State.SHIPPED,
            "Can only dispute from FUNDED or SHIPPED"
        );

        uint256 disputeId = disputes.length;
        Dispute storage d = disputes.push();
        d.orderId = orderId;
        d.reason = reason;
        d.votesForBuyer = 0;
        d.votesForSeller = 0;
        d.resolved = false;

        orders[orderId].state = State.DISPUTED;
        orders[orderId].disputeId = disputeId;

        emit OrderDisputed(orderId, msg.sender);
    }

    /**
     * 仲裁人投票
     *
     * [影子验证] 仲裁人身份 + 争议未解决 + 仲裁人未重复投票
     *
     * @param forBuyer true = 支持买家退款, false = 支持卖家收款
     */
    function voteOnDispute(uint256 orderId, bool forBuyer) external onlyArbitrator {
        Order memory shadow = orders[orderId];
        require(shadow.state == State.DISPUTED, "Order not in dispute");
        // disputeId 可以为 0 (第一个争议)，状态检查已保证争议存在

        uint256 disputeId = shadow.disputeId;
        Dispute storage dispute = disputes[disputeId];
        require(!dispute.resolved, "Dispute already resolved");
        require(!dispute.hasVoted[msg.sender], "Already voted");

        dispute.hasVoted[msg.sender] = true;
        if (forBuyer) {
            dispute.votesForBuyer++;
        } else {
            dispute.votesForSeller++;
        }

        emit DisputeVoted(disputeId, msg.sender, forBuyer);
    }

    /**
     * 执行仲裁裁决
     *
     * [影子验证] 在 memory 上统计票数 → 达到 2/3 阈值 → 原子执行资金清算
     * 裁决逻辑:
     *   - votesForBuyer >= 2  → 退款买家
     *   - votesForSeller >= 2 → 放款卖家
     *   - 未达阈值 → revert
     */
    function executeArbitration(uint256 orderId) external {
        Order memory shadow = orders[orderId];
        require(shadow.state == State.DISPUTED, "Order not in dispute");

        uint256 disputeId = shadow.disputeId;
        // disputeId 可以为 0 (第一个争议)

        Dispute storage dispute = disputes[disputeId];
        require(!dispute.resolved, "Already resolved");

        // 影子统计 → 原子决策
        if (dispute.votesForBuyer >= VOTE_THRESHOLD) {
            // 退款买家
            dispute.resolved = true;
            orders[orderId].state = State.COMPLETED;

            (bool sent, ) = payable(shadow.buyer).call{value: shadow.amount}("");
            require(sent, "Refund to buyer failed");

            emit DisputeResolved(disputeId, true);
        } else if (dispute.votesForSeller >= VOTE_THRESHOLD) {
            // 放款卖家
            dispute.resolved = true;
            orders[orderId].state = State.COMPLETED;

            (bool sent, ) = payable(shadow.seller).call{value: shadow.amount}("");
            require(sent, "Transfer to seller failed");

            emit DisputeResolved(disputeId, false);
        } else {
            revert("Vote threshold not reached");
        }
    }

    // ─── 查询接口 ─────────────────────────────────────────────────
    function getOrderCount() external view returns (uint256) {
        return orders.length;
    }

    function getDisputeVotes(uint256 orderId)
        external
        view
        returns (uint256 votesForBuyer, uint256 votesForSeller, bool resolved)
    {
        Order memory shadow = orders[orderId];
        Dispute storage d = disputes[shadow.disputeId];
        return (d.votesForBuyer, d.votesForSeller, d.resolved);
    }
}

/**
 * bytes32 地址大小比较 (内部库函数)
 */
function addressBytesLt(bytes32 a, bytes32 b) pure returns (bool) {
    return a < b;
}
