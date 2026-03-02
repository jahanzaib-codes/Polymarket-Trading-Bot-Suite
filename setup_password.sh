#!/bin/bash
# ╔══════════════════════════════════════════════╗
# ║  Polymarket Bot – Secure Credentials Setup  ║
# ╚══════════════════════════════════════════════╝
set -e

ENV_FILE="/home/Polymarket-Trading-Bot-Suite/.env"

echo ""
echo "============================================================"
echo "   Polymarket Bot — Dashboard Credentials Setup"
echo "============================================================"
echo ""
echo "This sets up username/password stored in the .env file."
echo "These credentials are NEVER pushed to GitHub."
echo ""

# ── Username ──────────────────────────────────────────────────────
read -p "  Enter dashboard username [default: admin]: " UNAME
UNAME="${UNAME:-admin}"

# ── Password ──────────────────────────────────────────────────────
while true; do
    read -s -p "  Enter dashboard password (min 8 chars): " PWD1
    echo ""
    if [ ${#PWD1} -lt 8 ]; then
        echo "  ❌ Password too short. Minimum 8 characters."
        continue
    fi
    read -s -p "  Confirm password: " PWD2
    echo ""
    if [ "$PWD1" = "$PWD2" ]; then
        break
    fi
    echo "  ❌ Passwords don't match. Try again."
done

# ── Write .env ────────────────────────────────────────────────────
cat > "$ENV_FILE" <<EOF
DASH_PASSWORD_ENABLED=true
DASH_USERNAME=${UNAME}
DASH_PASSWORD=${PWD1}
EOF

chmod 600 "$ENV_FILE"

echo ""
echo "============================================================"
echo "  ✅ Credentials saved to $ENV_FILE"
echo "  Username: ${UNAME}"
echo "  Password: (hidden)"
echo ""
echo "  Now restart the bot:"
echo "    bash /home/Polymarket-Trading-Bot-Suite/update.sh"
echo "============================================================"
echo ""
