# 校园二手交易平台 — 系统架构设计

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Single HTML5)                       │
│           Bootstrap 5 + ethers.js 6 + Tab 三合一视图              │
│     ┌──────────┐    ┌──────────┐    ┌──────────────┐            │
│     │ 买家视图  │    │ 卖家视图  │    │ 仲裁人视图    │            │
│     └────┬─────┘    └────┬─────┘    └──────┬───────┘            │
│          │               │                  │                    │
└──────────┼───────────────┼──────────────────┼────────────────────┘
           │               │                  │
           │  ethers.js    │  RPC calls       │
           ▼               ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│              Hardhat Local Node (EVM Compatible)                 │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ MerkleWhitelist  │  │   Escrow     │  │   MultiSig       │   │
│  │   (准入控制)      │◄─┤ (担保托管)    │──►│  (2/3 仲裁)      │   │
│  └──────────────────┘  └──────┬───────┘  └──────────────────┘   │
│                               │                                   │
└───────────────────────────────┼───────────────────────────────────┘
                                │  Events (OrderCreated, etc.)
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Off-Chain Relay (Python FastAPI)                 │
│  ┌──────────┐    ┌────────────────┐    ┌──────────────────┐     │
│  │ Web3.py  │───►│  Event Listener│───►│    SQLite DB     │     │
│  │Provider  │    │  (async poll)  │    │ (增量同步)        │     │
│  └──────────┘    └────────────────┘    └────────┬─────────┘     │
│                                                  │                │
│  ┌───────────────────────────────────────────────┘               │
│  │  REST API: /api/orders, /api/whitelist/proof/{id}             │
│  └───────────────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 合约层设计

### 2.1 MerkleWhitelist — 链下 Merkle 白名单准入

**设计理念**: 迁移自 `mybitcoin/src/Core/Merkle.cpp` 的两两哈希归约算法。

**合约存储**:
```solidity
contract MerkleWhitelist {
    bytes32 public merkleRoot;      // 仅存 32 字节的根
    mapping(bytes32 => bool) public usedLeafs;  // 防重放
    address public owner;
}
```

**验证算法** (等价于 Merkle.cpp 的 while-loop 归约):
```
function verify(bytes32[] proof, bytes32 leaf) → bool:
    computedHash = leaf
    for each proofElement in proof:
        if computedHash < proofElement:
            computedHash = keccak256(computedHash || proofElement)
        else:
            computedHash = keccak256(proofElement || computedHash)
    return computedHash == merkleRoot && !usedLeafs[leaf]
```

**叶子构造**: `leaf = keccak256(abi.encodePacked(studentId, deadline))`
- `studentId`: 学号
- `deadline`: 白名单有效期截止时间戳

**链下生成器** (`scripts/merkle_gen.py`) — 算法等价映射 Merkle.cpp:
```python
def compute_merkle_root(leaves: List[bytes32]) -> bytes32:
    if not leaves:
        return bytes32(0)
    hashes = leaves[:]
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:       # 奇数尾节点自复制
            hashes.append(hashes[-1])   # ← 直接对应 Merkle.cpp:16
        new_level = []
        for i in range(0, len(hashes), 2):
            concat = hashes[i] + hashes[i+1]
            new_level.append(keccak256(concat))  # ← 对应 Merkle.cpp:26 Hash256
        hashes = new_level
    return hashes[0]                    # ← 对应 Merkle.cpp:31
```

### 2.2 Escrow — 担保托管有限状态机

**状态转换图**:
```
                    ┌──────────────┐
                    │   CREATED    │ ← 卖家创建订单
                    └──────┬───────┘
                           │ buyer.fund(){value: price}
                           ▼
                    ┌──────────────┐
           ┌───────│   FUNDED     │
           │       └──────┬───────┘
           │              │ seller.ship()
           │              ▼
           │       ┌──────────────┐
           │       │   SHIPPED    │─────────────── timeout ─────┐
           │       └──────┬───────┘                             │
           │              │ buyer.receive()                      │
           │              ▼                                      │
           │       ┌──────────────┐                              │
           │       │  RECEIVED    │──► release() → COMPLETED    │
           │       └──────────────┘                              │
           │                                                    │
           │    ┌──────────────┐                                 │
           └───►│  DISPUTED    │◄── buyer.dispute() / seller    │
                └──────┬───────┘                                 │
                       │ 2/3 multisig approve                    │
                       ▼                                         │
                ┌──────────────┐                                 │
                │ ARBITRATING  │──► 通过 → COMPLETED (卖家收款)   │
                └──────────────┘──► 驳回 → FUNDED (退款买家)      │
```

**核心数据结构**:
```solidity
struct Order {
    address buyer;
    address seller;
    uint256 amount;
    State state;              // enum State { CREATED, FUNDED, SHIPPED, RECEIVED, COMPLETED, DISPUTED }
    uint256 shippedAt;        // 用于超时计算
    uint256 disputeId;        // 关联 MultiSig proposalId
}

mapping(uint256 => Order) public orders;
uint256 public orderCounter;
uint256 public constant SHIPPING_TIMEOUT = 7 days;
```

**影子状态验证** (借鉴 Blockchain.cpp:98 的原子提交模式):
```solidity
function _transitionState(uint256 orderId, State newState) internal {
    // [步骤 1] 创建影子副本 — 读取当前状态到内存
    Order memory shadow = orders[orderId];   // ← memory copy (影子账本)

    // [步骤 2] 在影子上验证状态转换合法性
    require(_isValidTransition(shadow.state, newState), "Invalid transition");

    // [步骤 3] 提交 — 只有验证通过才写入 storage
    orders[orderId].state = newState;        // ← commit (原子写入)
    emit StateChanged(orderId, shadow.state, newState);
}
```

### 2.3 MultiSig — 2/3 多签仲裁

**设计参数**:
- 仲裁人总数: 3 (校方代表 + 学生会代表 + 平台管理员)
- 通过阈值: 2/3
- 提案有效期: 72 小时

**合约结构**:
```solidity
contract MultiSig {
    address[] public arbitrators;  // [0]校方 [1]学生会 [2]平台
    uint256 public constant THRESHOLD = 2;
    uint256 public constant EXPIRY = 72 hours;

    struct Proposal {
        uint256 orderId;
        bool approveBuyer;       // true = 放款给买家, false = 放款给卖家
        uint256 approvals;
        uint256 expiresAt;
        mapping(address => bool) hasVoted;
        bool executed;
    }
}
```

---

## 3. 数据库逻辑结构 (SQLite)

```
┌──────────────┐       ┌──────────────────┐
│   orders     │       │    disputes      │
├──────────────┤       ├──────────────────┤
│ id (PK)      │◄──────│ order_id (FK)    │
│ contract_id  │       │ id (PK)          │
│ buyer        │       │ reason           │
│ seller       │       │ votes (JSON)     │
│ amount_wei   │       │ status           │
│ state        │       │ created_at       │
│ merkle_proof │       │ resolved_at      │
│ created_at   │       └──────────────────┘
│ updated_at   │
└──────────────┘

┌──────────────────┐
│  whitelist       │
├──────────────────┤
│ student_id (PK)  │
│ merkle_proof     │
│ deadline         │
│ used             │
└──────────────────┘
```

SQLite 的作用是**链下索引与快速查询**，不是权威数据源。权威状态始终在链上。中继只做增量同步，不修改状态。

---

## 4. 链下中继 (Python FastAPI) 设计

### 4.1 事件监听循环
```python
# relay/listener.py
async def listen_events(contract, db: sqlite3.Connection):
    """轮询 Hardhat 节点的事件日志，增量写入 SQLite"""
    last_block = get_last_synced_block(db)

    while True:
        current_block = w3.eth.block_number
        if current_block > last_block:
            events = contract.events.OrderCreated.get_logs(
                fromBlock=last_block + 1, toBlock=current_block
            )
            for evt in events:
                upsert_order(db, evt.args)  # INSERT OR REPLACE

            update_last_synced_block(db, current_block)
            last_block = current_block

        await asyncio.sleep(2)  # 2 秒轮询间隔
```

### 4.2 API 端点
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/orders` | 订单列表（支持 ?state=FUNDED 过滤） |
| GET | `/api/orders/{id}` | 单订单详情 |
| GET | `/api/whitelist/proof/{student_id}` | 获取学生的 Merkle Proof |
| GET | `/api/disputes` | 争议列表 |
| POST | `/api/disputes` | 创建争议（传入 order_id, reason） |

---

## 5. 前端 H5 架构

```
index.html (单文件，CDN 引入所有依赖)
├── <head>
│   ├── Bootstrap 5 CDN CSS
│   └── ethers.js 6 CDN
├── <body>
│   ├── Navbar (角色切换 Tab: 买家 | 卖家 | 仲裁人)
│   ├── Tab: BuyerView (商品列表 → Merkle 验证 → 下单 → 收货)
│   ├── Tab: SellerView (发布商品 → 订单管理 → 发货)
│   ├── Tab: ArbitratorView (争议列表 → 投票面板)
│   └── <script>
│       ├── Wallet 连接模块 (connectWallet)
│       ├── 合约 ABI 与地址配置
│       ├── Merkle 验证流程 (fetch proof → contract.verify)
│       ├── 买家操作 (createOrder, fund, receive)
│       ├── 卖家操作 (listItem, ship)
│       └── 仲裁操作 (loadDisputes, vote)
└── </body>
```

**关键交互流程**:
1. 连接 MetaMask → 检测 chainId=31337 (Hardhat)
2. 买家选择商品 → 前端调用 `/api/whitelist/proof/{studentId}` → 传入合约 verify()
3. verify() 通过后 → createOrder() → fund() → 等待卖家 ship()
4. 争议时 → dispute() → 仲裁人投票 → MultiSig.execute() → Escrow 收到裁决

---

## 6. 安全设计要点

| 层面 | 措施 |
|------|------|
| 重入攻击 | 所有状态变更使用 CEI (Checks-Effects-Interactions) 模式，借鉴影子账本先验证后提交 |
| 前端篡改 | Merkle Proof 由服务端签发，前端不可伪造；白名单验证在合约层二次校验 |
| 双花 | `usedLeafs` mapping 防 Merkle Proof 重放；订单状态机禁止逆向转换 |
| 超时死锁 | SHIPPED 状态超时后自动完成；MultiSig 提案过期后自动失效 |
| 女巫攻击 | 白名单与学生身份绑定，一人一叶 |

---

## 7. 学术创新点

1. **Merkle 白名单准入**: 将比特币区块头验证的密码学原语迁移至应用层身份认证，链上仅存 32 字节 Root，Gas 节省 90%+ 对比链上存储方案
2. **影子账本状态隔离**: 借鉴 `Blockchain.cpp:98` 的 `tempUTXO` 原子提交模式，所有状态转换在 memory 副本完成验证后一次性写入 storage，消除中间状态不一致窗口
3. **2/3 多签博弈均衡**: 三方制衡 — 校方权威 + 学生自治 + 平台中立，任意两方合谋仍无法单独作恶
