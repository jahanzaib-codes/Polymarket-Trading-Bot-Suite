#!/bin/bash
# ============================================================
#  Polymarket Bot — Password Setup Script
#  Run once to enable dashboard password protection on VPS
#  Usage:  bash setup_password.sh
# ============================================================

BOT_DIR="/home/Polymarket-Trading-Bot-Suite"
ENV_FILE="$BOT_DIR/.env"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}============================================================${NC}"
echo -e "${YELLOW}   Polymarket Bot — Password Protection Setup${NC}"
echo -e "${YELLOW}============================================================${NC}"
echo ""

# Ask for password
read -s -p "Enter dashboard password (min 8 chars): " PASSWORD
echo ""

if [ ${#PASSWORD} -lt 8 ]; then
    echo "❌ Password too short. Must be at least 8 characters."
    exit 1
fi

read -s -p "Confirm password: " PASSWORD2
echo ""

if [ "$PASSWORD" != "$PASSWORD2" ]; then
    echo "❌ Passwords do not match."
    exit 1
fi

# Write .env file
cat > "$ENV_FILE" << EOF
# Polymarket Bot Dashboard — Security Config
# This file is NOT uploaded to GitHub (in .gitignore)
DASH_PASSWORD_ENABLED=true
DASH_PASSWORD=$PASSWORD
EOF

chmod 600 "$ENV_FILE"

echo ""
echo -e "${GREEN}✅ Password saved to $ENV_FILE${NC}"
echo -e "${GREEN}   File permissions set to 600 (owner only)${NC}"
echo ""
echo "Now restart the bot:"
echo -e "${YELLOW}  bash update.sh${NC}"
echo ""
