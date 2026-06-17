#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
HARDHAT_URL="http://127.0.0.1:8545"
RELAY_PORT=8000
FRONTEND_PORT=3000

cleanup() {
  echo ""
  echo "Shutting down..."
  kill $NODE_PID $RELAY_PID $FRONTEND_PID 2>/dev/null
  wait $NODE_PID $RELAY_PID $FRONTEND_PID 2>/dev/null
  echo "All services stopped."
}
trap cleanup EXIT INT TERM

echo "============================================"
echo "  Campus Secondhand DApp — 一键启动"
echo "============================================"

# ─── 1. Hardhat Node ───────────────────────────────────────────
echo ""
echo "[1/3] Starting Hardhat node (port 8545)..."
npx hardhat node > /tmp/hardhat-node.log 2>&1 &
NODE_PID=$!

# Wait until RPC is ready
echo -n "      Waiting for RPC"
for i in $(seq 1 30); do
  if curl -s -X POST -H "Content-Type: application/json" \
       -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
       "$HARDHAT_URL" > /dev/null 2>&1; then
    echo " ready"
    break
  fi
  echo -n "."
  sleep 1
done

# ─── 2. Deploy contracts ───────────────────────────────────────
echo ""
echo "[2/3] Deploying contracts..."
cd "$ROOT"
python3 relay/deploy.py --hardhat-url "$HARDHAT_URL"

# ─── 3. Relay (FastAPI) ────────────────────────────────────────
echo ""
echo "[3/3] Starting relay API (port $RELAY_PORT)..."
uvicorn relay.main:app --host 127.0.0.1 --port $RELAY_PORT > /tmp/relay.log 2>&1 &
RELAY_PID=$!
sleep 1

# ─── 4. Frontend Server ────────────────────────────────────────
echo ""
echo "Starting frontend (http://localhost:$FRONTEND_PORT)..."
cd "$ROOT/frontend"
python3 -m http.server $FRONTEND_PORT > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!

echo ""
echo "============================================"
echo "  All services running!"
echo ""
echo "  Hardhat Node : $HARDHAT_URL"
echo "  Relay API    : http://localhost:$RELAY_PORT"
echo "  Frontend     : http://localhost:$FRONTEND_PORT"
echo ""
echo "  API docs     : http://localhost:$RELAY_PORT/docs"
echo "  Health check : http://localhost:$RELAY_PORT/health"
echo "============================================"
echo ""
echo "Press Ctrl+C to stop all services."

# Wait for any process to exit
wait
