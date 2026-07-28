#!/usr/bin/env bash
# TradeLead Hunter 启动脚本 — 本地 / 服务器通用
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"

HOST="${LEADHUNTER_HOST:-0.0.0.0}"
PORT="${LEADHUNTER_PORT:-8866}"

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
  UV=.venv/bin/uvicorn
elif command -v python3 >/dev/null; then
  PY=python3
  UV="python3 -m uvicorn"
else
  echo "需要 Python 3.10+"
  exit 1
fi

# 读 config.yaml 端口（若未设环境变量）
if [ -z "${LEADHUNTER_PORT:-}" ] && [ -f config.yaml ]; then
  cfg_port=$($PY -c "import yaml;print(yaml.safe_load(open('config.yaml')).get('server',{}).get('port',8866))" 2>/dev/null || echo 8866)
  PORT="$cfg_port"
fi

echo "TradeLead Hunter  starting on http://${HOST}:${PORT}"
exec $UV app.main:app --host "$HOST" --port "$PORT"
