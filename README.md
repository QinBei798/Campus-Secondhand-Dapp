<p align="center">
  <img src="https://img.shields.io/badge/Solidity-0.8.20-363636?logo=solidity&logoColor=white" alt="Solidity">
  <img src="https://img.shields.io/badge/Hardhat-2.28-fff100?logo=hardhat&logoColor=black" alt="Hardhat">
  <img src="https://img.shields.io/badge/Python-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Web3.py-6.x-bc4b38?logo=python&logoColor=white" alt="Web3.py">
  <img src="https://img.shields.io/badge/ethers.js-v6-2535a0?logo=ethers&logoColor=white" alt="ethers.js v6">
  <img src="https://img.shields.io/badge/SQLite-3.x-003b57?logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/TDD-22%2F22%20PASS-brightgreen" alt="Tests">
</p>

<h1 align="center">
  🎓 基于区块链的校园二手交易平台
</h1>
<h3 align="center">
  <em>Campus Secondhand DApp — Trustless Escrow &amp; Merkle Sybil-Resistance on EVM</em>
</h3>

---

## 📖 目录

- [💡 背景痛点与区块链真刚需](#-背景痛点与区块链真刚需)
- [🏗️ 系统创新架构映射](#️-系统创新架构映射)
- [🔐 合约核心状态机流转](#-合约核心状态机流转)
- [📂 项目文件结构](#-项目文件结构)
- [🚀 极速本地跑通与联调指南](#-极速本地跑通与联调指南)
- [🎬 2 分钟期末答辩 Live Demo 黄金脚本](#-2-分钟期末答辩-live-demo-黄金脚本)
- [🧪 测试矩阵](#-测试矩阵)
- [📚 学术创新点与密码学代码复用](#-学术创新点与密码学代码复用)
- [🔒 安全设计](#-安全设计)

---

## 💡 背景痛点与区块链真刚需

传统校园二手交易平台依赖中心化 MySQL + 后端架构，在以下四个维度存在系统性缺陷。本系统基于以太坊 EVM 智能合约逐一击破，论证去中心化架构在该场景下的**不可替代性**。

<table>
<tr><th width="140">痛点维度</th><th>中心化架构缺陷</th><th>区块链解决方案</th></tr>

<tr>
<td><strong>🔴 资金池法律风险</strong></td>
<td>

平台私设账户沉淀交易资金，形成**非法资金池**（参照《非银行支付机构监督管理条例》），面临监管取缔风险。

</td>
<td>

<b>无组织资产托管</b> — 资金锁定在智能合约地址中，平台 <b>从不持有</b> 用户资金。买家付款直接转入合约托管，卖家收款由合约原子释放。零资金池、零挪用风险。

</td>
</tr>

<tr>
<td><strong>🔴 运维续费依赖</strong></td>
<td>

服务器 + 数据库需持续付费。学生毕业后平台无人维护，**数据库断代丢失**，历年交易声誉全部蒸发。

</td>
<td>

<b>服务器零运维续费长生特性</b> — 合约部署在以太坊兼容链上即永久存活。前端为纯静态 HTML，可托管于 IPFS / GitHub Pages 等零成本基础设施。**跨学生世代传承**，无需任何组织持续付费。

</td>
</tr>

<tr>
<td><strong>🔴 声誉不可篡改</strong></td>
<td>

中心化数据库的评分、交易记录可由管理员一行 SQL 任意改写。刷单、删差评、买好评**零密码学成本**。

</td>
<td>

<b>密码学不可洗白的声誉矩阵</b> — 所有交易状态变更以链上 Event Log 形式永久铭刻。白名单准入由 Merkle Root 锚定，单次身份验证消费（`usedLeafs` mapping）不可重置。虚假声誉的伪造代价等价于攻破 `keccak256` 原像抗性。

</td>
</tr>

<tr>
<td><strong>🔴 仲裁暗箱操作</strong></td>
<td>

单一管理员拥有绝对裁决权。交易纠纷中管理员可偏袒一方，无任何制衡机制。

</td>
<td>

<b>2/3 多签仲裁机制</b> — 三方制衡：校方代表 + 学生会代表 + 平台管理员。任意单方无法单独裁决，需 <b>≥2 方达成共识</b> 方可执行资金清算。投票记录全链可审计，彻底杜绝暗箱操作。

</td>
</tr>
</table>

---

## 🏗️ 系统创新架构映射

### 读写通路混合分离架构

```
                          ┌─────────────────────────────┐
                          │        Frontend (SPA)         │
                          │   Bootstrap 5 + ethers.js 6   │
                          │   ┌───────┬───────┬───────┐   │
                          │   │ Buyer │Seller │Arbiter│   │
                          │   └───┬───┴───┬───┴───┬───┘   │
                          └───────┼───────┼───────┼───────┘
                                  │       │       │
                  ┌───────────────┼───────┼───────┼───────────────┐
                  │               │       │       │               │
                  │   ✍️ WRITE PATH (签名交易)     │               │
                  │   ethers.js → MetaMask → RPC   │               │
                  │               │       │       │               │
                  │               ▼       ▼       ▼               │
                  │   ┌──────────────────────────────────┐        │
                  │   │     Hardhat Local EVM Node        │        │
                  │   │  ┌──────────┐  ┌──────────────┐  │        │
                  │   │  │Merkle    │  │  CampusEscrow │  │        │
                  │   │  │Whitelist │◄─┤  (FSM Engine) │  │        │
                  │   │  │(32-byte  │  │               │  │        │
                  │   │  │ Root)    │  │ 2/3 MultiSig  │  │        │
                  │   │  └──────────┘  └───────┬───────┘  │        │
                  │   └──────────────────────────┼────────┘        │
                  │                              │ Events          │
                  └──────────────────────────────┼─────────────────┘
                                                 │
                  ┌──────────────────────────────┼─────────────────┐
                  │                              ▼                 │
                  │   📖 READ PATH (高并发缓存层)                   │
                  │   ┌──────────────────────────────────┐        │
                  │   │   FastAPI Off-Chain Relay          │        │
                  │   │   ┌────────────┐  ┌────────────┐  │        │
                  │   │   │ Event      │  │  REST API   │  │        │
                  │   │   │ Listener   │──►  Endpoints  │  │        │
                  │   │   │ (Daemon)   │  │ /api/orders │  │        │
                  │   │   └─────┬──────┘  │ /api/whitelist│      │
                  │   │         │         │ /api/disputes│      │
                  │   │         ▼         └──────┬───────┘  │        │
                  │   │   ┌────────────┐         │          │        │
                  │   │   │  SQLite DB │◄────────┘          │        │
                  │   │   │ (Read Cache│                    │        │
                  │   │   │  + Proofs) │                    │        │
                  │   │   └────────────┘                    │        │
                  │   └──────────────────────────────────────┘        │
                  │                                                  │
                  └──────────────────────────────────────────────────┘
```

**设计哲学**：

| 通路 | 特性 | 延迟 | 适用场景 |
|------|------|------|----------|
| **写通路** (链上) | 签名交易 → EVM 共识 → 状态变更 | ~2s / 区块 | 创建订单、付款、发货、争议 |
| **读通路** (链下) | 事件监听器增量同步 → SQLite 索引 | <10ms | 商品列表、订单查询、Merkle Proof 签发 |

写通路保证**权威性与不可篡改性**，读通路保证**高并发低延迟的用户体验**。SQLite 是纯缓存，权威状态始终在链上。

### 密码学代码复用：Merkle 白名单准入

本系统的 Merkle 树实现直接迁移自自研 C++ 迷你比特币项目 [`mybitcoin/src/Core/Merkle.cpp`](https://github.com/QinBei798/mybitcoin)，在 Python 层复刻其两两归约哈希算法：

```
mybitcoin/src/Core/Merkle.cpp          scripts/merkle_gen.py
══════════════════════════════         ════════════════════
ComputeMerkleRoot()                   compute_merkle_root()
  ├─ 拷贝交易ID列表                     ├─ hashes = leaves[:]
  ├─ while(hashes.size() > 1)          ├─ while len(hashes) > 1:
  ├─ 奇数尾节点自复制                    ├─ if len(hashes) % 2 != 0: hashes.append(hashes[-1])
  ├─ for(i=0; i<size; i+=2)            ├─ for i in range(0, len(hashes), 2):
  ├─ Hash256(left+right)               ├─ keccak256(sorted(left, right) + concat)
  └─ return hashes[0]                  └─ return hashes[0]

验证公式 (合约层):
  computedHash = leaf
  for each proofElement in proof:
      if computedHash < proofElement:
          computedHash = keccak256(computedHash || proofElement)
      else:
          computedHash = keccak256(proofElement || computedHash)
  require(computedHash == merkleRoot)
```

**学术贡献**：将比特币区块头验证的原语迁移至应用层身份认证，链上仅存储 32 字节 `merkleRoot`，达成以下量化优势：

- **Gas 节省**: 对比链上白名单 mapping 存储（~20,000 gas/地址），10,000 名学生仅需 1 次 `SSTORE`（20,000 gas），节省 **99.9%+**
- **防女巫攻击**: 叶子哈希绑定 `keccak256(studentId, deadline)`，一人一叶 + `usedLeafs` 防重放
- **隐私保护**: 学生信息不出现在链上，仅以哈希承诺形式存在
- **验证复杂度**: $\mathcal{O}(\log N)$ — 10,000 名学生仅需约 14 次 `keccak256` 即可完成验证

---

## 🔐 合约核心状态机流转

### 资金托管有限状态自动机 (DFA)

```
                        ┌──────────────────────────────────────────┐
                        │                                          │
    ┌──────────┐  fund  │  ┌──────────┐  ship  ┌──────────┐        │
    │ CREATED  │───────┘  │  FUNDED  │───────►│ SHIPPED  │        │
    └──────────┘          └────┬─────┘        └────┬─────┘        │
     卖家挂牌                 │                    │               │
                              │ dispute            │ receive        │
                              ▼                    ▼               │
                        ┌──────────┐         ┌──────────┐         │
                        │ DISPUTED │         │ RECEIVED │         │
                        └────┬─────┘         └────┬─────┘         │
                             │                    │                │
                             │ 2/3 vote           │ release()      │
                             ▼                    ▼                │
                        ┌──────────────────────────────────┐       │
                        │          COMPLETED                │◄──────┘
                        │  (卖家收款 / 买家退款)             │
                        └──────────────────────────────────┘
```

### 状态转换矩阵

| 当前状态 | 触发操作 | 调用者 | 下一状态 | 资金行为 |
|----------|----------|--------|----------|----------|
| `CREATED` | `fundOrder()` | Buyer | `FUNDED` | ETH 锁定在合约 |
| `FUNDED` | `shipOrder()` | Seller | `SHIPPED` | — |
| `FUNDED` | `raiseDispute()` | Buyer | `DISPUTED` | 资金冻结 |
| `SHIPPED` | `receiveOrder()` | Buyer | `COMPLETED` | 释放给 Seller |
| `SHIPPED` | `raiseDispute()` | Buyer | `DISPUTED` | 资金冻结 |
| `DISPUTED` | 2/3 vote → `executeArbitration()` | Arbiter | `COMPLETED` | 按票数方向释放 |

### 影子账本原子提交范式

借鉴 `mybitcoin/src/Core/Blockchain.cpp:98` 的 `tempUTXO` 原子提交模式，所有状态转换遵循三阶段协议：

```solidity
// [Phase 1] 深度拷贝 — 从 storage 读取到 memory (影子账本)
Order memory shadow = orders[orderId];

// [Phase 2] 影子验证 — 在 memory 副本上校验权限 + 状态合法性
require(shadow.buyer == msg.sender, "Only buyer");
require(shadow.state == State.CREATED, "Invalid state transition");

// [Phase 3] 原子提交 — 所有验证通过后一次性写入 storage
orders[orderId].state = State.FUNDED;
```

此范式消除中间状态不一致窗口，防止竞态条件下的重入攻击与状态回滚。

---

## 📂 项目文件结构

```
campus-secondhand-dapp/
├── contracts/                    # Solidity 智能合约
│   ├── MerkleWhitelist.sol       #   Merkle 白名单准入 (32字节 Root)
│   └── CampusEscrow.sol          #   担保托管 + 2/3 多签仲裁引擎
│
├── scripts/                      # Python 工具链
│   └── merkle_gen.py             #   Merkle 树生成器 (算法移植自 Merkle.cpp)
│
├── relay/                        # 链下中继层 (Python FastAPI)
│   ├── main.py                   #   REST API 服务入口 + 端点定义
│   ├── listener.py               #   事件监听器守护线程 (增量同步)
│   ├── db.py                     #   SQLite 数据库层 (WAL 模式)
│   ├── models.py                 #   Pydantic 请求/响应模型
│   ├── deploy.py                 #   自动化合约部署脚本
│   └── deploy.json               #   部署输出 (合约地址 + Merkle Root)
│
├── test/                         # 智能合约测试套件 (Hardhat + Chai)
│   └── CampusEscrow.test.js      #   22 条 TDD 测试 (A.1-A.5, B.1-B.4)
│
├── frontend/                     # 前端 H5 控制台
│   └── index.html                #   单页三合一视图 (Buyer / Seller / Arbiter)
│
├── docs/                         # 设计文档
├── start.sh                      # 一键启动脚本 (Hardhat + Deploy + Relay + Frontend)
├── hardhat.config.js             # Hardhat 本地链配置 (chainId: 31337)
├── package.json                  # Node.js 依赖
└── .gitignore                    # 已隔离 *.db, .venv/, artifacts/, cache/, node_modules/
```

---

## 🚀 极速本地跑通与联调指南

### 环境要求

| 组件 | 版本 | 用途 |
|------|------|------|
| Node.js | ≥18.x | Hardhat 编译 + 测试 |
| Python | ≥3.10 | FastAPI 中继 + 部署脚本 |
| MetaMask | 任意版本 | 浏览器钱包签名 |

### 零、安装依赖（仅首次）

```bash
npm install
pip install fastapi uvicorn web3 pydantic
npx hardhat compile
```

### 一、一键启动（推荐）

```bash
./start.sh
```

自动完成：启动 Hardhat 节点 → 部署合约 → 启动 API 中继 → 启动前端服务器。

打开 `http://localhost:3000`，在 MetaMask 中切换到 `localhost:8545` (Chain ID: `31337`)，即可开始使用。`Ctrl+C` 一键停止所有服务。

前端合约地址自动从 relay `/api/config` 动态加载，**无需手动修改任何配置**。

### 二、手动启动（分步调试）

```bash
# 终端 1: 本地链
npx hardhat node

# 终端 2: 部署合约
python3 relay/deploy.py

# 终端 2: 启动中继（自动读取 relay/deploy.json 中的合约地址）
uvicorn relay.main:app --port 8000

# 终端 3: 前端静态服务器
cd frontend && python3 -m http.server 3000
```

### 三、运行测试

```bash
npx hardhat test
# 预期输出: 22 passing (MerkleWhitelist x5, CampusEscrow x17)
```

---

## 🎬 2 分钟期末答辩 Live Demo 黄金脚本

以下为评委/教授现场演示的精确路线，按时间戳逐帧执行。提前准备好三个 MetaMask 账户（买家、卖家、仲裁人1）以支持快速角色切换。

> **准备**：确保 Hardhat 节点 + FastAPI 中继已在后台运行。

### ⏱️ 0:00–0:15 — 开场：白名单注册

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | MetaMask 切换到 **卖家账户** (Account #2) | 右上角地址变更为卖家 |
| 2 | 点击 **Seller** Tab | 界面切换到卖家视图 |
| 3 | 点击 `Register Whitelist` 按钮 | MetaMask 弹窗 → Confirm |
| 4 | 等待 tx 确认 | 页面提示 "Whitelisted!" |

> **口播**："卖家首先通过 Merkle 白名单验证，前端自动从 Relay 获取该地址的 Merkle Proof，提交到链上智能合约进行零知识风格的密码学验证。链上仅存储 32 字节的 Root，验证复杂度是 log N。"

### ⏱️ 0:15–0:40 — 正向交易闭环

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 5 | 在 Seller 视图填写商品信息 → 选择买家地址 → `Create Order` | 订单卡片出现在列表中，状态 = `CREATED` |
| 6 | MetaMask 切换到 **买家账户** (Account #1) → 点击 **Buyer** Tab | 界面切换到买家视图 |
| 7 | 在买家视图中看到该订单 → 点击 `Fund` | MetaMask 确认付款 (1 ETH) |
| 8 | 等待 tx 确认 | 订单状态 → `FUNDED` (资金锁定在合约) |
| 9 | MetaMask 切回 **卖家** → 点击 `Ship` | 状态 → `SHIPPED` |
| 10 | MetaMask 切回 **买家** → 点击 `Receive` | 状态 → `COMPLETED`，卖家收到 ETH |

> **口播**："整个交易闭环在 20 秒内完成。资金从未经过平台服务器，全程在智能合约中物理隔离。这是传统中心化架构无法实现的——无组织资产托管。"

### ⏱️ 0:40–1:10 — 争议仲裁演示（核心亮点）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 11 | 卖家创建新订单 → 买家付款 → 买家点击 `Dispute`，填写原因 | 状态 → `DISPUTED` |
| 12 | MetaMask 切换到 **仲裁人1** (Account #3) → 点击 **Arbiter** Tab | 仲裁面板显示争议列表 |
| 13 | 仲裁人1 投票 ✅ **支持买家** | 票数: Buyer=1, Seller=0 |
| 14 | MetaMask 切换到 **仲裁人2** (Account #4) → 同样投票 ✅ **支持买家** | 票数: Buyer=2, Seller=0 |
| 15 | 点击 `Execute Arbitration` | 票数 ≥ 2/3 阈值 → 资金退回买家 |

> **口播**："争议发生后，任意单个仲裁人无法单独裁决——需要 3 方中至少 2 方达成共识。这是博弈均衡设计：校方、学生会、平台管理员三方制衡，任何两方合谋也无法单独作恶。"

### ⏱️ 1:10–1:45 — 负面测试（展示防御能力）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 16 | 用未注册白名单的账户尝试 `Create Order` | MetaMask revert: `Not whitelisted` |
| 17 | 用非买家账户尝试 `Fund` | revert: `Only buyer` |
| 18 | 用非仲裁人账户尝试 `Vote` | revert: `Only arbitrator can vote` |

> **口播**："三次攻击尝试全部被智能合约的影子验证机制拦截。每个操作在执行前都会创建一个内存影子副本进行权限和状态合法性校验，只有全部通过后才原子写入链上存储——消除中间状态不一致的安全窗口。"

### ⏱️ 1:45–2:00 — 收尾

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 19 | 打开终端运行 `npx hardhat test` | 22/22 passing |
| 20 | `curl http://localhost:8000/api/orders` | JSON 列表展示全部链上订单已同步 |

> **口播**："22 条 TDD 测试全绿通过，覆盖白名单验证、正向交易流程、争议仲裁路径、影子状态防护、以及权限拦截矩阵。链下中继层的 SQLite 通过事件监听器实时同步链上状态，为用户提供毫秒级的查询体验。"

---

## 🧪 测试矩阵

### 合约层 (Hardhat + Chai + ethers.js v6)

| 套件 | 编号 | 测试用例 | 覆盖维度 |
|------|------|----------|----------|
| **Suite A** | A.1 | Valid Merkle proof → returns true | 密码学验证 |
| MerkleWhitelist | A.2 | Forged proof → revert "Invalid proof" | 防伪造 |
| (5 tests) | A.3 | Double-use same leaf → revert | 防重放 |
| | A.4 | Address not in tree → revert | 防非成员 |
| | A.5 | Mismatched nonce → revert | 防过期身份 |
| **Suite B** | B.1.1 | Full lifecycle CREATED→COMPLETED | 正向流程 |
| CampusEscrow | B.1.2 | Funds transferred to seller on completion | 资金清算 |
| (17 tests) | B.2.1 | Buyer raises dispute from FUNDED | 争议入口 |
| | B.2.2 | State = DISPUTED after dispute | 状态变更 |
| | B.2.3 | 2/3 vote refunds buyer | 多签裁决 |
| | B.3.1 | Non-buyer fund → revert "Only buyer" | 权限拦截 |
| | B.3.2 | Non-seller ship → revert "Only seller" | 权限拦截 |
| | B.3.3 | Non-buyer receive → revert "Only buyer" | 权限拦截 |
| | B.3.4 | Non-arbitrator vote → revert | 角色隔离 |
| | B.3.5 | Wrong state transition → revert | 状态机防护 |
| | B.4.1 | Non-whitelisted seller → revert | 白名单集成 |
| | B.4.2 | Hacker fund → revert "Only buyer" | 身份伪造防御 |

### 中继层 (Python pytest)

| 测试 | 覆盖 |
|------|------|
| 数据库 CRUD 操作 | `init_db`, `upsert_order`, `get_orders`, `get_order` |
| 争议 API | `create_dispute`, `get_disputes` |
| Merkle Proof 签发 | `generate_whitelist`, `verify_proof` 自检 |

---

## 📚 学术创新点与密码学代码复用

### 创新点 1：Merkle 白名单准入 — 从比特币区块验证到应用层身份认证

将比特币 SPV 轻节点验证的密码学原语迁移至校园身份准入场景。算法的 Python 复刻与 Solidity 验证构成跨语言密码学管线：

```
┌──────────────────────────────────────────────────────────────┐
│                 Cross-Language Merkle Pipeline                │
│                                                              │
│  mybitcoin/src/Core/      scripts/merkle_gen.py    Solidity   │
│     Merkle.cpp         ════════════════════════   Contract    │
│  ┌──────────────┐      ┌────────────────────┐  ┌──────────┐  │
│  │ ComputeMerkle│─────►│ compute_merkle_root │─►│ verify() │  │
│  │   Root()     │ 移植  │ (Python 逐行复刻)    │  │ (链上    │  │
│  └──────────────┘      └─────────┬──────────┘  │  验证)   │  │
│                                  │              └──────────┘  │
│                                  ▼                           │
│                        ┌────────────────────┐                │
│                        │ generate_proof()   │                │
│                        │ (Proof 路径数组)    │                │
│                        └────────────────────┘                │
└──────────────────────────────────────────────────────────────┘
```

### 创新点 2：影子账本原子提交 — 消除智能合约中间状态窗口

借鉴 `Blockchain.cpp:98` 中 `tempUTXO` 的原子化交易验证模式，在所有状态变更函数中强制执行 "Deep Copy → Validate → Commit" 三阶段协议。所有业务逻辑在 EVM `memory` 副本上完成校验，仅在全部通过后以单次 `SSTORE` 写入 `storage`。

### 创新点 3：2/3 多方博弈均衡仲裁

三方制衡的设计使得：
- **(校方, 学生会)** 合谋无法绕过平台
- **(校方, 平台)** 合谋无法绕过学生自治
- **(学生会, 平台)** 合谋无法绕过校方权威

任意单方背叛 → 剩余两方可形成有效多数，保障裁决永远需要跨利益群体共识。

---

## 🔒 安全设计

| 攻击向量 | 防御措施 | 实现位置 |
|----------|----------|----------|
| **重入攻击** | CEI (Checks-Effects-Interactions) — 状态变更先于 `call{}` 转账 | `CampusEscrow.sol:193` |
| **前端篡改** | Merkle Proof 由中继层签发，合约层二次校验 | `MerkleWhitelist.sol:46` |
| **双花 / 重放** | `usedLeafs` mapping 防 Merkle Proof 重放；状态机禁止逆向转换 | 合约全局 |
| **超时死锁** | 争议无超时限制 (仲裁人可随时投票)；提案设计预留 `expiresAt` 扩展 | `CampusEscrow.sol` |
| **女巫攻击** | 白名单与学生身份绑定，叶哈希 `keccak256(studentId, deadline)` 一人一叶 | `scripts/merkle_gen.py:29` |
| **整数溢出** | Solidity ^0.8.20 内置 SafeMath | 编译器原生 |
| **未授权访问** | `onlyBuyer` / `onlySeller` / `onlyArbitrator` 三阶 modifier 矩阵 | `CampusEscrow.sol:64-86` |

---

<p align="center">
  <sub>
    Built with ❤️ by <a href="https://github.com/QinBei798">QinBei798</a> —
    Merkle algorithm lineage: <code>mybitcoin/src/Core/Merkle.cpp</code> → <code>scripts/merkle_gen.py</code> → <code>contracts/MerkleWhitelist.sol</code>
  </sub>
</p>
