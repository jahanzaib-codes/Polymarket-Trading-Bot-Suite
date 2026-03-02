#!/bin/bash
# ╔══════════════════════════════════════════════════╗
# ║  Polymarket Bot – Auto Update & Restart Script  ║
# ╚══════════════════════════════════════════════════╝
set -e
BOT_DIR="/home/Polymarket-Trading-Bot-Suite"
VENV="$BOT_DIR/venv"
LOG="$BOT_DIR/bot.log"
SCREEN_NAME="polymarket"

echo ""
echo "============================================================"
echo "   Polymarket Bot — Auto Update & Restart"
echo "============================================================"

# ── Step 1: Kill everything on port 5000 + ALL old screens ───────
echo ""
echo "[1/5] Stopping existing bot process..."
fuser -k 5000/tcp 2>/dev/null && echo "  ✅ Stopped process on port 5000" || echo "  ℹ️  Port 5000 was not in use"

# Kill ALL screen sessions (including old 'myapp' etc.)
screen -ls 2>/dev/null | grep -oP '\d+\.\S+' | while read s; do
    screen -X -S "$s" quit 2>/dev/null && echo "  ✅ Closed screen: $s"
done
sleep 1

# ── Step 2: Pull latest code ──────────────────────────────────────
echo ""
echo "[2/5] Pulling latest code from GitHub..."
cd "$BOT_DIR"
git fetch --all
git reset --hard origin/main
echo "  ✅ Code updated to: $(git log -1 --format='%h %s')"

# ── Step 3: Update dependencies ───────────────────────────────────
echo ""
echo "[3/5] Updating Python packages..."
source "$VENV/bin/activate"
pip install -r requirements.txt -q --upgrade
echo "  ✅ Dependencies up to date"

# ── Step 4: Check .env ────────────────────────────────────────────
echo ""
echo "[4/5] Checking security config..."
ENV_FILE="$BOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    UNAME=$(grep DASH_USERNAME "$ENV_FILE" | cut -d= -f2)
    echo "  ✅ .env found — username: ${UNAME:-admin} | password: (hidden)"
else
    echo "  ⚠️  No .env file — creating default (admin / admin123)"
    cat > "$ENV_FILE" <<EOF
DASH_PASSWORD_ENABLED=true
DASH_USERNAME=admin
DASH_PASSWORD=admin123
EOF
    chmod 600 "$ENV_FILE"
    echo "  ℹ️  Run: bash setup_password.sh  to change credentials"
fi

# ── Step 5: Start bot ─────────────────────────────────────────────
echo ""
echo "[5/5] Starting bot in background (screen)..."
> "$LOG"  # clear old log
screen -dmS "$SCREEN_NAME" bash -c "source $VENV/bin/activate && cd $BOT_DIR && python app.py >> $LOG 2>&1"
sleep 4

# Verify it started
if fuser 5000/tcp > /dev/null 2>&1; then
    echo ""
    echo "============================================================"
    echo "  ✅ Bot started successfully!"
    echo "  Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo '144.217.18.203'):5000"
    echo "  View logs: screen -r $SCREEN_NAME"
    echo "  Live tail:  tail -f $LOG"
    echo "  Detach:    Ctrl+A then D"
    echo "============================================================"
else
    echo ""
    echo "  ❌ Bot may have crashed. Check logs:"
    echo "  tail -50 $LOG"
    tail -30 "$LOG" 2>/dev/null || true
fi
echo ""
