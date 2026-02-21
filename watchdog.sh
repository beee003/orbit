#!/bin/bash
# Watchdog: keeps ngrok and the backend server alive
# Usage: bash watchdog.sh

BACKEND_PORT=8000
NGROK_LOG=/tmp/ngrok.log
SERVER_LOG=/tmp/orbit-server.log
CHECK_INTERVAL=5

echo "ORBIT Watchdog started"

while true; do
    # Check backend server
    if ! lsof -ti :$BACKEND_PORT > /dev/null 2>&1; then
        echo "$(date): Backend down, restarting..."
        cd /Users/user/orbit/backend
        DD_LLMOBS_ENABLED=1 DD_LLMOBS_ML_APP=Orbit \
        DD_API_KEY=d0c46532015dd393c6df0c8b488328de \
        DD_SITE=us5.datadoghq.com \
        DD_LLMOBS_AGENTLESS_ENABLED=1 \
        DD_SERVICE=orbit DD_ENV=hackathon \
        nohup /Users/user/Library/Python/3.12/bin/ddtrace-run \
        uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT >> $SERVER_LOG 2>&1 &
        sleep 3
    fi

    # Check ngrok
    NGROK_OK=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('tunnels',[])))" 2>/dev/null)
    if [ "$NGROK_OK" != "1" ]; then
        echo "$(date): ngrok down, restarting..."
        pkill -f "ngrok http" 2>/dev/null
        sleep 1
        nohup ngrok http $BACKEND_PORT --log $NGROK_LOG --log-format logfmt > /dev/null 2>&1 &
        sleep 4
        URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" 2>/dev/null)
        echo "$(date): ngrok URL: $URL"
    fi

    sleep $CHECK_INTERVAL
done
