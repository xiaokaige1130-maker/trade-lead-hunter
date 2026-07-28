#!/usr/bin/env bash
cd /home/hyk/外贸获客台 || exit 1
URL="http://127.0.0.1:8866/"
if ! curl -s -m 1 http://127.0.0.1:8866/api/health 2>/dev/null | grep -q '"ok"'; then
  echo "启动 TradeLead Hunter..."
  fuser -k 8866/tcp >/dev/null 2>&1 || true
  nohup ./start.sh > /tmp/lead-hunter.log 2>&1 &
  echo $! > /tmp/lead-hunter.pid
  for i in $(seq 1 40); do
    curl -s -m 1 http://127.0.0.1:8866/api/health 2>/dev/null | grep -q '"ok"' && break
    sleep 0.4
  done
fi
xdg-open "$URL" >/dev/null 2>&1 &
echo "打开 $URL"
