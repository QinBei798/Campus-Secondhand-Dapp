# 基于 Geth PoA 联盟链的交易溯源与区块链浏览器详情设计方案

本设计方案旨在为“校园二手交易平台”升级**链上交易实时溯源时间线**与**迷你区块链浏览器详情弹窗**功能。

方案基于当前已部署的 **Docker Geth Clique PoA 四节点私有联盟链网络**（1 Bootnode + 3 Sealers/Validators，3秒出块周期），抛弃了过于简单、不合规的 Hardhat 单机内存仿真环境，确保符合课程/学术报告的分布式系统高标准要求。

---

## 一、 系统架构图 (Architecture)

本功能采用 **“链上数据共识 ── 链下事件监听与持久化 ── 按需 RPC 详情查询”** 的混合架构：

```
+--------------------------------------------------------------+
|                    前端浏览器 (MetaMask)                      |
|  [我卖的/全校在售商品卡片] ---> 展示交易时间线                 |
|  [点击交易哈希] ------------> 弹出 Etherscan 详情弹窗        |
+------------------------------+-------------------------------+
                               | API 请求
                               v
+------------------------------+-------------------------------+
|                    后端中继层 (FastAPI API)                   |
|  - GET /api/orders (获取含历史哈希 of 订单列表)                 |
|  - GET /api/tx/{tx_hash} (实时向 Geth 查询交易/收据细节)     |
+---------------+------------------------------+---------------+
                | 读取/写入                    | JSON-RPC
                v                              v
+---------------+---------------+      +-------+---------------+
|     SQLite 缓存 (relay.db)     |      | Geth 联盟网络 (NodeA) |
|  - orders (订单主表)          |      |  - 实时区块/交易数据   |
|  - order_tx_history (轨迹表)   |      |  - 智能合约状态        |
+-------------------------------+      +-----------------------+
```

---

## 二、 数据库结构设计 (Database Schema)

在 `relay/db.py` 中新增 `order_tx_history` 表，用于记录订单生命周期内每一个状态变更交易对应的哈希和区块号：

```sql
CREATE TABLE IF NOT EXISTS order_tx_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_order_id INTEGER NOT NULL,  -- 关联的合约订单 ID
    action TEXT NOT NULL,                -- 动作类型: 'CREATED', 'FUNDED', 'SHIPPED', 'COMPLETED', 'DISPUTED', 'RESOLVED'
    tx_hash TEXT NOT NULL,               -- 该动作的交易哈希 (0x...)
    block_number INTEGER NOT NULL,       -- 打包该交易的区块高度
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contract_order_id) REFERENCES orders(contract_id)
);
```

### 数据库层操作函数
- `insert_tx_history(contract_order_id, action, tx_hash, block_number)`：新增一条历史状态记录（防止重复插入）。
- `get_tx_history_by_order(contract_order_id)`：根据订单 ID 查询其所有的历史轨迹，按 `block_number` 升序排列。

---

## 三、 后端中继与事件同步设计 (Backend & Sync)

### 1. 监听器升级 (`relay/listener.py`)
在事件监听器的回调函数中，不仅要更新订单的主状态，还要同步将交易的元数据存入历史表：

- **`handle_order_created`**:
  写入 `action='CREATED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。
- **`handle_order_funded`**:
  写入 `action='FUNDED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。
- **`handle_order_shipped`**:
  写入 `action='SHIPPED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。
- **`handle_order_received`**:
  写入 `action='COMPLETED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。
- **`handle_order_disputed`**:
  写入 `action='DISPUTED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。
- **`handle_dispute_resolved`**:
  通过交易解码得到 `orderId` 后，写入 `action='RESOLVED'`, `tx_hash=event.transactionHash.hex()`, `block_number=event.blockNumber`。

### 2. API 路由设计 (`relay/main.py`)

#### 接口一：`GET /api/orders`
- **逻辑变更**：在返回订单列表时，利用 SQL `LEFT JOIN` 或在 Python 中查询 `order_tx_history` 表，将每个订单的历史轨迹序列化为列表嵌套在订单数据中。
- **返回 JSON 结构示例**：
  ```json
  [
    {
      "contract_id": 1,
      "buyer": "0xf39F...",
      "seller": "0x3C44...",
      "amount_wei": "1000000000000000000",
      "state": "SHIPPED",
      "description": "测试商品",
      "history": [
        {"action": "CREATED", "tx_hash": "0x1111...", "block_number": 1583},
        {"action": "FUNDED", "tx_hash": "0x2222...", "block_number": 1589},
        {"action": "SHIPPED", "tx_hash": "0x3333...", "block_number": 1592}
      ]
    }
  ]
  ```

#### 接口二：`GET /api/tx/{tx_hash}` (按需链上实时查询)
- **逻辑**：后端接收到前端的交易哈希后，直接通过 Web3.py 向本地 Geth 联盟链节点查询完整的收据和区块数据。
- **核心实现代码**：
  ```python
  @app.get("/api/tx/{tx_hash}")
  async def get_transaction_details(tx_hash: str):
      try:
          # 1. 获取交易详情
          tx = w3.eth.get_transaction(tx_hash)
          # 2. 获取交易收据 (拿到实际 Gas 消耗与状态)
          receipt = w3.eth.get_transaction_receipt(tx_hash)
          # 3. 获取区块信息 (拿到精确时间戳)
          block = w3.eth.get_block(tx.blockNumber)
          
          return {
              "status": receipt["status"],  # 1 为成功，0 为失败
              "block_number": tx["blockNumber"],
              "block_hash": tx["blockHash"].hex(),
              "from": tx["from"],
              "to": tx["to"],
              "value_eth": w3.from_wei(tx["value"], "ether"),
              "gas_used": receipt["gasUsed"],
              "gas_price_gwei": w3.from_wei(tx["gasPrice"], "gwei"),
              "timestamp": block["timestamp"] # 转化为人类可读的时间戳
          }
      except Exception as e:
          raise HTTPException(status_code=404, detail=f"Transaction not found on-chain: {str(e)}")
  ```

---

## 四、 前端界面与交互设计 (Frontend UI/UX)

### 1. 历史时间线渲染 (Timeline UI)
在“我正在卖的物品”与“全校在售物品”板块中，在原本仅显示“当前状态”的位置，展开渲染一个直观的横向/纵向时间线小组件。
- 状态节点使用不同的图标区分（如：创建=📦，付款=💰，发货=🚚，完成=✅）。
- 区块高度以气泡标签形式高亮显示（例如：`Block #1583`）。
- 点击哈希文本直接触发弹出详情。

### 2. 迷你区块链浏览器弹窗 (Etherscan Modal)
当用户点击时间线上的任一交易哈希（如 `0x1111...`）时，前端捕获点击事件并弹出遮罩弹窗。
- **设计风格**：采用 Sleek Modern 磨砂玻璃（Glassmorphism）暗色调设计，排版对齐真正的 Etherscan 详情页。
- **弹窗内容字段**：
  - **Transaction Hash**: `0x1111...` (附带一键复制按钮)
  - **Status**: `🟢 Success` 或 `🔴 Fail`
  - **Block**: `#1583` (Block Hash: `0xabc...`)
  - **Timestamp**: `2026-06-19 18:00:03 (Local)`
  - **From / To**: `0x3474...` $\rightarrow$ `0x0b83... (CampusEscrow)`
  - **Value**: `1.0 ETH`
  - **Gas Fee**: `45,120 gas`

### 3. 前端影子 Mock 数据开关 (Debug Mode)
在前端 JS 代码最上方增加 `const MOCK_UI_TEST = false;`：
- 当开启时，点击交易哈希不请求后端，直接使用一组本地写好的 Etherscan 假数据进行弹窗展示。这极大地便利了 UI 样式的快速还原与排版微调。

---

## 五、 分步实施与验证计划 (Implementation & Verification)

### 第一阶段：后端数据库扩展与接口 Mock 开发
1. 修改 `relay/db.py`，新增 `order_tx_history` 表和增删改查函数。
2. 修改 `relay/main.py`，编写 `/api/tx/{tx_hash}` 接口，先用 Mock 数据返回，以便前端能立刻集成。
3. **验证方式**：在浏览器访问 `http://localhost:8000/docs`（FastAPI Swagger UI），通过 API 交互式页面“Try it out”测试接口是否能成功返回 Mock 数据。

### 第二阶段：前端 UI 还原与影子数据调试
1. 在 `frontend/index.html` 中实现时间线组件样式。
2. 绘制 Etherscan 风格的 Modal 弹窗，并开启前端 `MOCK_UI_TEST = true`。
3. **验证方式**：手动点击界面，微调弹窗的 CSS 阴影、磨砂透明度、字体和复制按钮反馈，确保视觉效果惊艳、交互流畅。

### 第三阶段：后端区块链监听器接入与去 Mock 化
1. 修改 `relay/listener.py`，将真实的 `blockNumber` 和 `transactionHash` 写入数据库历史表。
2. 去掉 `relay/main.py` 路由中的 Mock 挡板，改为真实的 Web3.py 链上查询。
3. 将前端 `MOCK_UI_TEST` 设为 `false`。
4. **验证方式**：启动 `./start.sh` 和 `monitor.py`，发起一次真实交易。在页面上观察：
   - 订单下方的区块号是否与 `monitor.py` 终端中亮起的区块号完全一致。
   - 点击哈希，弹窗中展示的 `Gas Used` 等数据是否与链上真实数据完全对齐。
