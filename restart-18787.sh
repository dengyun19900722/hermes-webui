#!/bin/bash
# 重启 hermes-webui 18787

PID=$(lsof -ti:18787 2>/dev/null)
if [ -n "$PID" ]; then
    echo "Killing PID $PID on port 18787..."
    kill $PID 2>/dev/null
    sleep 1
fi

echo "Starting server on port 18787..."
cd /Users/dengyun/workspace/hermes-webui-dev/hermes-webui
/Users/dengyun/.hermes/hermes-agent/venv/bin/python server.py --port 18787 >> /tmp/hermes-18787.log 2>&1 &

sleep 2
if curl -s -o /dev/null -w "%{http_code}" http://localhost:18787/ | grep -q "200"; then
    echo "Server is UP on http://localhost:18787"
else
    echo "Server may have failed. Check /tmp/hermes-18787.log"
fi