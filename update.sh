#!/bin/bash
# ============================================================
#  Polymarket Trading Bot Suite — Auto Update & Restart Script
#  Usage:  bash update.sh
#  Run once to update code from GitHub and restart the bot.
# ============================================================

set -e

BOT_DIR="/home/Polymarket-Trading-Bot-Suite"
SCREEN_NAME="polymarket"
PORT=5000
VENV="$BOT_DIR/venv/bin/python"
LOG_FILE="$BOT_DIR/bot.log"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}   Polymarket Bot — Auto Update & Restart${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""

# ── Step 1: Kill whatever is on port 5000 ──────────────────
echo -e "${YELLOW}[1/5] Stopping existing bot process...${NC}"
fuser -k $PORT/tcp 2>/dev/null && echo "  ✅ Stopped process on port $PORT" || echo "  ℹ️  No process on port $PORT"

# Kill existing screen session if any
screen -S $SCREEN_NAME -X quit 2>/dev/null && echo "  ✅ Closed screen session" || true
sleep 1

# ── Step 2: Pull latest code from GitHub ───────────────────
echo ""
echo -e "${YELLOW}[2/5] Pulling latest code from GitHub...${NC}"
cd $BOT_DIR
git pull origin main
echo "  ✅ Code updated"

# ── Step 3: Update Python dependencies ─────────────────────
echo ""
echo -e "${YELLOW}[3/5] Updating Python packages...${NC}"
source $BOT_DIR/venv/bin/activate
pip install -r requirements.txt --quiet --upgrade
echo "  ✅ Dependencies up to date"

# ── Step 4: Load password from .env if present ─────────────
echo ""
echo -e "${YELLOW}[4/5] Checking security config...${NC}"
if [ -f "$BOT_DIR/.env" ]; then
    echo "  ✅ .env file found — password protection will be applied"
else
    echo "  ⚠️  No .env file — dashboard is PUBLIC (no password)"
    echo "     Run: bash setup_password.sh  to enable password protection"
fi

# ── Step 5: Start bot in a screen session ──────────────────
echo ""
echo -e "${YELLOW}[5/5] Starting bot in background (screen)...${NC}"
screen -dmS $SCREEN_NAME bash -c "
    cd $BOT_DIR
    source venv/bin/activate
    python app.py 2>&1 | tee -a $LOG_FILE
"
sleep 3

# ── Verify it started ──────────────────────────────────────
if screen -list 2>/dev/null | grep -q "$SCREEN_NAME"; then
    SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "YOUR_VPS_IP")
    echo ""
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}  ✅ Bot started successfully!${NC}"
    echo -e "${GREEN}  Dashboard: http://$SERVER_IP:$PORT${NC}"
    echo -e "${GREEN}  View logs: screen -r $SCREEN_NAME${NC}"
    echo -e "${GREEN}  Detach:    Ctrl+A then D${NC}"
    echo -e "${GREEN}============================================================${NC}"
else
    echo ""
    echo -e "${RED}  ❌ Bot may have crashed. Check logs:${NC}"
    echo -e "${RED}  tail -50 $LOG_FILE${NC}"
fi
echo ""
