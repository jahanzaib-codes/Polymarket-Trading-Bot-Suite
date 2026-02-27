# Polymarket Trading Bot Suite

> **Two fully automated trading bots for Polymarket** — a Copy Trading Bot and a High-Probability Entry Bot — with a web-based control panel for monitoring and configuration.

---


## 🤖 Bot 1 — Copy Trading Bot

Monitors a target Polymarket trader's activity in real-time and automatically mirrors their trades using your capital.

### Features

- **Real-time monitoring** of a target trader's positions via Polymarket Data API
- **Proportional sizing** — scales the copy trade relative to the original size using a configurable ratio
- **Risk-managed execution** — enforces max trade size, min trade size, and max position count
- **Stop-loss per position** — configurable percentage-based stop-loss on every opened position
- **Daily & weekly loss limits** — halts trading when cumulative losses reach threshold
- **Emergency stop** — instantly halts all trading activity
- **Audit trail** — every action (copy, skip, stop-loss) is logged with full details

### Key Parameters

| Parameter             | Default                                     | Description                          |
| --------------------- | ------------------------------------------- | ------------------------------------ |
| Target Trader Address | —                                          | Wallet address of the trader to copy |
| Total Capital (USDC)  | 1000                                        | Total allocated capital              |
| Capital Allocation %  | 50%                                         | Percentage used per trade            |
| Copy Ratio            | 0.10                                        | Mirror 10% of target's trade size    |
| Max Trade Size        | $200                                        | Hard cap per single trade            |
| Min Trade Size        | $5                                          | Ignore trades smaller than this      |
| Stop Loss %           | 20%                                         | Auto-close if position drops 20%     |
| Daily Loss Limit      | $100 | Pause trading after $100 daily loss  |                                      |
| Weekly Loss Limit     | $300 | Pause trading after $300 weekly loss |                                      |
| Max Open Positions    | 10                                          | Never hold more than 10 positions    |
| Poll Interval         | 5s                                          | How often to check for new trades    |

---

## 🤖 Bot 2 — High-Probability Entry Bot

Continuously scans all active Polymarket events and automatically enters positions when any market side reaches a configurable probability threshold (default 90¢).

### Strategy

- **Mean Reversion Mode** *(default)*: When a market side hits ≥90¢, the bot bets on the **opposite** side, capitalizing on the likelihood that extreme probabilities will revert toward equilibrium.
- **Momentum Mode**: Enters the *same* direction as the high-probability side.

### Features

- Scans **all active markets** on every cycle
- Configurable **entry threshold** (default: 0.90)
- Liquidity & volume filters to avoid low-quality markets
- **Take-profit** at a configurable gain %
- **Stop-loss** per position
- Daily & weekly loss limits
- Emergency stop
- Full signal log with reason for every detected event

### Key Parameters

| Parameter          | Default                             | Description                            |
| ------------------ | ----------------------------------- | -------------------------------------- |
| Entry Threshold    | 0.90                                | Enter when any side reaches this price |
| Position Size      | $50                                 | Default trade size                     |
| Max Position Size  | $200                                | Maximum per single position            |
| Strategy Mode      | Mean Reversion                      | Bet opposite or same direction         |
| Stop Loss %        | 15%                                 | Auto-close on loss                     |
| Take Profit %      | 5%                                  | Auto-close on gain                     |
| Daily Loss Limit   | $150 | Pause after $150 daily loss  |                                        |
| Weekly Loss Limit  | $400 | Pause after $400 weekly loss |                                        |
| Max Open Positions | 5                                   | Max concurrent positions               |
| Min Liquidity      | $1,000                              | Skip illiquid markets                  |
| Min 24h Volume     | $500                                | Skip low-volume markets                |
| Scan Interval      | 10s                                 | Market scan frequency                  |

---

## 🌐 Web Dashboard

The control panel runs locally on **http://localhost:5000** and provides:

| Section                 | Description                                                 |
| ----------------------- | ----------------------------------------------------------- |
| **Overview**      | Live stats for both bots — PnL, open positions, daily loss |
| **Credentials**   | Enter Polygon wallet & API keys securely                    |
| **Copy Bot**      | Configure, start/stop, view positions & trade history       |
| **High-Prob Bot** | Configure, start/stop, view positions & signal history      |
| **Audit Log**     | Combined log of all bot actions, exportable as CSV          |

---

## ⚙️ Installation

### 1. Prerequisites

- Python 3.10+
- A Polygon (MATIC) wallet with USDC

### 2. Clone / Download

Place all files in a folder, e.g., `harshilsyndiate/`

### 3. Install Dependencies

```bash
pip install flask flask-socketio requests py-clob-client
```

> **Note**: `py-clob-client` is the official Polymarket Python SDK. Without it the bots run in **paper-trading / read-only mode** — all logic executes but no real orders are placed.

### 4. Run the Dashboard

```bash
python app.py
```

Open your browser at **http://localhost:5000**

---

## 🔐 API Credentials Setup

### Getting your keys

1. **Fund a Polygon wallet** with USDC (recommended: MetaMask or a Gnosis Safe)
2. **Visit** [polymarket.com](https://polymarket.com) and connect your wallet
3. **Generate API credentials** from your profile → Settings → API
4. Enter them in the **Credentials** page of the dashboard

### Credential fields

| Field          | Description                                                     |
| -------------- | --------------------------------------------------------------- |
| Private Key    | Your Polygon wallet private key (`0x...`)                     |
| API Key        | From Polymarket API settings                                    |
| API Secret     | From Polymarket API settings                                    |
| API Passphrase | From Polymarket API settings                                    |
| Funder Address | *Optional* – your Safe wallet address if using a Gnosis Safe |

> ⚠️ **Security**: Never share your private key. Store credentials securely. The dashboard stores them in memory only — they are never written to disk.

---

## 🔒 Risk Management

Both bots implement multiple layers of protection:

1. **Position-level stop-loss** — every position has a stop price
2. **Max position count** — never open more than N positions simultaneously
3. **Daily loss limit** — trading halts when daily losses exceed threshold
4. **Weekly loss limit** — trading halts when weekly losses exceed threshold
5. **Emergency stop** — one-click halt of all trading (via dashboard button)
6. **Min trade size** — ignores copy signals too small to be meaningful
7. **Liquidity filters** (HP Bot) — avoids entering illiquid markets

---

## 📡 Polymarket API Reference

| API       | URL                                                | Purpose                             |
| --------- | -------------------------------------------------- | ----------------------------------- |
| Gamma API | `https://gamma-api.polymarket.com`               | Market discovery & metadata         |
| CLOB API  | `https://clob.polymarket.com`                    | Order book, prices, order placement |
| Data API  | `https://data-api.polymarket.com`                | User positions, trade history       |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/` | Real-time market updates            |

---

## 📋 Dependencies

```
flask
flask-socketio
requests
py-clob-client   # Official Polymarket Python SDK
```

---

## ⚠️ Disclaimer

- **Use at your own risk.** Prediction market trading carries significant financial risk.
- Ensure compliance with **Polymarket Terms of Service** in your jurisdiction.
- This software is provided for **educational and demonstration purposes**.
- Always test with small amounts before deploying with real capital.
- The developers are not responsible for any financial losses.

---

## 📞 Support

For questions regarding configuration, API setup, or custom modifications, refer to:

- [Polymarket Docs](https://docs.polymarket.com)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
