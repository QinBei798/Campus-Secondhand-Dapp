# 校园二手交易平台 — 全栈开发排期

> **总工期**: 4 天（周一下午 → 周四晚，周五预留联调 buffer）
> **模式**: Vibe Coding + TDD（先写边界拦截测试，再写业务逻辑）

---

## Day 1（周一 6/14）：基础设施搭建 + 合约层核心

### Task 0: 项目脚手架初始化
- [ ] `npx hardhat init` 初始化合约工程
- [ ] `pip install fastapi uvicorn web3 py-solc-x sqlite3` Python 中继环境
- [ ] 创建前端单文件 `frontend/index.html`
- [ ] `.gitignore` 补充（node_modules, __pycache__, artifacts, cache）

### Task 1: Merkle 白名单合约 + Python 证明生成器
**文件**: `contracts/MerkleWhitelist.sol`, `scripts/merkle_gen.py`

- [ ] **TDD**: 先写 Hardhat 测试 `test/merkle.test.js`
  - 测试用例：空列表应 revert、有效 proof 通过、无效 proof revert、重放攻击拦截
- [ ] 编写 `MerkleWhitelist.sol`
  - 存储 Merkle Root（由 owner 设置）
  - `verify(bytes32[] proof, bytes32 leaf)` 纯函数，两两哈希归约 → 比对 root
  - 使用 `keccak256(abi.encodePacked(studentId, timestamp))` 为叶子
- [ ] 编写 `scripts/merkle_gen.py`
  - 输入：白名单 CSV (学号列表)
  - 输出：Merkle Root + 每个用户的 Proof
  - 算法迁移自 `Merkle.cpp`：叶子层 → while len > 1 → 两两 concat + hash → 奇数尾复制
- [ ] `npx hardhat test test/merkle.test.js` 全绿

### Task 2: 担保托管有限状态机合约
**文件**: `contracts/Escrow.sol`

状态机：
```
CREATED → FUNDED → SHIPPED → RECEIVED → COMPLETED
                    ↓                    ↑
                 DISPUTED → ARBITRATING ↗ (via 2/3 multisig)
```

- [ ] **TDD**: `test/escrow.test.js`
  - 正向流程：CREATED→FUNDED→SHIPPED→RECEIVED→COMPLETED 全路径
  - 异常拦截：非买家不能 funded、非卖家不能 shipped、非买家不能 received
  - 争议路径：任意方可 dispute → 进入 DISPUTED → 仲裁投票通过 → COMPLETED
  - 边界：重复 funded revert、未 funded 时 shipped revert、仲裁中非仲裁人投票 revert
- [ ] 编写 `Escrow.sol`
  - 枚举 `State { CREATED, FUNDED, SHIPPED, RECEIVED, COMPLETED, DISPUTED }`
  - 状态转换修饰符 `onlyInState(State s)`, `onlyBuyer`, `onlySeller`, `onlyArbitrator`
  - 资金托管：`fund()` 转入合约，`release()` 转给卖家，`refund()` 退给买家
  - 超时机制：`SHIPPED` 状态 N 天后买家未确认 → 卖家可申请自动完成
  - **影子状态验证**：借鉴 `Blockchain.cpp:98` 的影子账本模式 — 所有状态变更先用 local copy 模拟，验证通过后再写入 storage
- [ ] `npx hardhat test test/escrow.test.js` 全绿

### Task 3: 2/3 多签仲裁合约
**文件**: `contracts/MultiSig.sol`

- [ ] **TDD**: `test/multisig.test.js`
  - 2/3 签名通过执行、1/3 不足 revert、重复签名拒绝、过期提案 revert
- [ ] 编写 `MultiSig.sol`
  - `submitProposal(bytes32 txHash)` → 返回 proposalId
  - `approve(uint256 proposalId)` → 累计确认数
  - `execute(uint256 proposalId)` → 确认数 >= 2 且未过期 → 执行
  - 与 Escrow 合约交互：`Escrow(msg.sender).resolveDispute(...)`
- [ ] `npx hardhat test test/multisig.test.js` 全绿

---

## Day 2（周二 6/15）：合约联调 + 链下中继

### Task 4: 合约集成测试 + Hardhat 本地链部署
- [ ] `scripts/deploy.js` — 一次性部署 MerkleWhitelist + Escrow + MultiSig
- [ ] `test/integration.test.js` — 全流程集成测试：
  白名单用户 → 创建订单 → 托管付款 → 发货 → 争议 → 2/3 仲裁 → 放款
- [ ] `npx hardhat node` 启动本地链，`npx hardhat run scripts/deploy.js --network localhost` 部署

### Task 5: Python FastAPI 链下中继
**文件**: `relay/main.py`, `relay/db.py`, `relay/listener.py`

- [ ] **TDD**: `relay/test_relay.py` (pytest)
  - `test_listen_escrow_created`: mock Web3 event → 断言 DB 写入
  - `test_sync_order_state`: 模拟链上状态变更 → 断言 SQLite 同步
- [ ] `relay/db.py` — SQLite ORM (sqlite3)
  ```sql
  CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    contract_addr TEXT,
    buyer TEXT, seller TEXT,
    amount_wei INTEGER,
    state TEXT,
    merkle_proof TEXT,  -- JSON array
    created_at TIMESTAMP,
    updated_at TIMESTAMP
  );
  CREATE TABLE disputes (
    id INTEGER PRIMARY KEY,
    order_id INTEGER,
    reason TEXT,
    votes TEXT,  -- JSON {arbitrator: vote}
    resolved_at TIMESTAMP
  );
  ```
- [ ] `relay/listener.py` — Web3.py 异步事件监听
  - 监听 `OrderCreated`, `OrderFunded`, `OrderShipped`, `OrderReceived`, `OrderDisputed`, `OrderResolved`
  - 每个事件 → 增量更新 SQLite
- [ ] `relay/main.py` — FastAPI 端点
  - `GET /api/orders` — 全部订单列表
  - `GET /api/orders/{id}` — 单订单详情 + 状态
  - `GET /api/whitelist/proof/{student_id}` — 查询 Merkle Proof
  - `POST /api/disputes` — 提交仲裁请求
- [ ] `pytest relay/test_relay.py -v` 全绿

---

## Day 3（周三 6/16）：前端 H5 控制台 + 端到端集成

### Task 6: 单文件三合一 H5 控制台
**文件**: `frontend/index.html`

单文件包含买家/卖家/仲裁人三种角色视图，Tab 切换。

- [ ] 技术选型：CDN 引入 Bootstrap 5 + ethers.js 6
- [ ] 三 Tab 布局：
  - **买家视图**: 浏览商品 → 选择 → 提交 Merkle Proof → 托管付款 → 确认收货
  - **卖家视图**: 发布商品 → 等待付款 → 确认发货
  - **仲裁人视图**: 查看争议列表 → 投票 (Approve/Reject) → 查看多签状态
- [ ] Metamask 钱包连接 (`ethers.BrowserProvider`)
- [ ] 与 Hardhat 本地链交互（chainId 31337）
- [ ] Merkle Proof 验证流程：
  用户输入学号 → 前端调用 `/api/whitelist/proof/{id}` 获取 proof → 调用合约 `verify()` → 通过后方可交易

### Task 7: 端到端集成测试
- [ ] 手动 E2E 流程：
  1. `npx hardhat node` → 部署合约
  2. `python relay/main.py` → 启动中继
  3. 打开 `frontend/index.html` → 连接 MetaMask (Hardhat 账户)
  4. 买家下单 → 卖家发货 → 买家收货 → 完成
  5. 争议场景：买家 dispute → 2 位仲裁人投票 → 裁决执行
- [ ] 记录并修复集成问题

---

## Day 4（周四 6/17）：汇报准备 + Buffer

### Task 8: PPT 素材与学术亮点提炼
- [ ] Merkle 白名单性能对比数据（链上存储 vs 链下 Proof）
- [ ] 影子账本状态隔离的安全论证
- [ ] 2/3 多签的游戏论分析（为什么不是 1/2 或 3/3）

### Task 9: 边界加固 + Gas 优化
- [ ] 重入攻击防护检查（CEI 模式）
- [ ] 整数溢出检查（Solidity ^0.8.0 已内置）
- [ ] Gas 消耗对比测试

### Task 10: 最终联调 + README
- [ ] 全链路一键启动脚本 `start.sh`
- [ ] `README.md` 含架构图、启动步骤、API 文档

---

## 风险点与缓解

| 风险 | 缓解 |
|------|------|
| Hardhat 本地链不稳定 | 备选 Ganache CLI |
| ethers.js v6 API 不熟悉 | 提前打印 Cheatsheet |
| MetaMask 连接 Hardhat 异常 | 重置账户 nonce |
| 时间不足 | 优先保证核心流程（托管+仲裁），Merkle 白名单作为亮点独立演示 |

---

> **Commit 策略**: 每个 Task 完成后立即 `git commit`，粒度细便于回溯。
