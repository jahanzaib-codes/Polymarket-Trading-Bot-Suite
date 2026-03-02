"""
Polymarket Trading Bots - Configuration File
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PolymarketConfig:
    """Main configuration for Polymarket API connection."""
    # API endpoints
    CLOB_HOST: str = "https://clob.polymarket.com"
    GAMMA_HOST: str = "https://gamma-api.polymarket.com"
    DATA_HOST: str = "https://data-api.polymarket.com"
    WS_HOST: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"

    # Polygon network
    CHAIN_ID: int = 137  # Polygon Mainnet

    # Credentials (set via environment variables or GUI)
    PRIVATE_KEY: str = ""
    API_KEY: str = ""
    API_SECRET: str = ""
    API_PASSPHRASE: str = ""
    FUNDER_ADDRESS: str = ""  # Optional: if using a Safe wallet


@dataclass
class CopyBotConfig:
    """Configuration for the Copy Trading Bot."""
    # Target trader to copy
    TARGET_TRADER_ADDRESS: str = ""

    # Capital Management
    TOTAL_CAPITAL_USDC: float = 1000.0       # Total allocated capital in USDC
    CAPITAL_ALLOCATION_PCT: float = 50.0      # % of capital to use per trade
    MAX_TRADE_SIZE_USDC: float = 200.0        # Max single trade size in USDC
    MIN_TRADE_SIZE_USDC: float = 5.0          # Min single trade size in USDC

    # Risk Management
    MAX_RISK_PER_TRADE_PCT: float = 5.0       # Max risk % per trade
    STOP_LOSS_PCT: float = 20.0               # Stop-loss % per position
    DAILY_LOSS_LIMIT_USDC: float = 100.0      # Max daily loss
    WEEKLY_LOSS_LIMIT_USDC: float = 300.0     # Max weekly loss
    MAX_OPEN_POSITIONS: int = 10              # Max open positions at once

    # Trade Sizing (proportional to target trader's position)
    PROPORTIONAL_SIZING: bool = True          # Scale trades proportionally
    COPY_RATIO: float = 0.10                  # Copy 10% of target's position size

    # Polling interval for checking new trades (seconds)
    POLL_INTERVAL_SECONDS: float = 5.0

    # Emergency stop
    EMERGENCY_STOP: bool = False


@dataclass
class HighProbBotConfig:
    """Configuration for the High-Probability Entry Bot."""
    # Entry price RANGE (in dollars, 0.00–1.00)
    # Bot triggers when price is between MIN and MAX (inclusive)
    # Example: MIN=0.88 MAX=0.91 → enters at 88-91 cents only (sweet spot for reversion)
    # Prices above MAX (e.g. $0.999) are TOO extreme and skipped
    ENTRY_THRESHOLD_MIN: float = 0.88         # Lower bound — don't enter below this
    ENTRY_THRESHOLD_MAX: float = 0.91         # Upper bound — don't enter above this (avoids $0.99)

    # Order execution
    ORDER_TYPE: str = "MARKET"                # "MARKET" = instant fill, "LIMIT" = GTC at range midpoint
    # For LIMIT orders: limit price = midpoint of (ENTRY_THRESHOLD_MIN + ENTRY_THRESHOLD_MAX) / 2
    # e.g. range 0.88-0.91 → limit at 0.895 for YES side, 0.105 for NO side

    # Position sizing
    DEFAULT_POSITION_SIZE_USDC: float = 50.0  # Default trade size in USDC
    MAX_POSITION_SIZE_USDC: float = 200.0     # Max single position size

    # Risk Management
    STOP_LOSS_PCT: float = 15.0               # Stop-loss % per position
    TAKE_PROFIT_PCT: float = 5.0              # Take-profit % (near $1.00)
    DAILY_LOSS_LIMIT_USDC: float = 150.0      # Max daily loss
    WEEKLY_LOSS_LIMIT_USDC: float = 400.0     # Max weekly loss
    MAX_OPEN_POSITIONS: int = 5               # Max high-prob positions at once

    # Market Filtering
    MIN_LIQUIDITY_USDC: float = 500.0         # Min market liquidity required
    MIN_VOLUME_USDC: float = 100.0            # Min 24h volume required
    ACTIVE_MARKETS_ONLY: bool = True          # Only trade active (open) markets
    MAX_HOURS_TO_CLOSE: float = 0.0           # Only scan markets closing within N hours (0 = DISABLED, scan ALL markets)

    # Strategy
    MEAN_REVERSION_MODE: bool = True          # True=bet opposite side, False=follow momentum

    # Monitoring interval (seconds)
    SCAN_INTERVAL_SECONDS: float = 30.0       # Scan every 30s (avoid rate limits)

    # Emergency stop
    EMERGENCY_STOP: bool = False


@dataclass
class DashboardConfig:
    """Web dashboard security settings."""
    CREDENTIALS_FILE: str = "credentials.json"  # Where to persist API keys locally
    PASSWORD_ENABLED: bool = False               # Enable dashboard password protection
    DASHBOARD_PASSWORD: str = "changeme123"      # Password for the dashboard
    SESSION_SECRET: str = ""                      # Auto-generated on first run


# Global default config instances
polymarket_config = PolymarketConfig()
copy_bot_config = CopyBotConfig()
high_prob_config = HighProbBotConfig()
dashboard_config = DashboardConfig()
