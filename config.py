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
    # Price threshold (in dollars, 0.90 = 90 cents)
    ENTRY_THRESHOLD: float = 0.90             # Enter when price >= this value

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
    MIN_LIQUIDITY_USDC: float = 1000.0        # Min market liquidity required
    MIN_VOLUME_USDC: float = 500.0            # Min 24h volume required
    ACTIVE_MARKETS_ONLY: bool = True          # Only trade active (open) markets

    # Mean Reversion strategy settings
    MEAN_REVERSION_MODE: bool = True          # Trade the opposing side for reversion

    # Monitoring interval (seconds)
    SCAN_INTERVAL_SECONDS: float = 10.0

    # Emergency stop
    EMERGENCY_STOP: bool = False


# Global default config instances
polymarket_config = PolymarketConfig()
copy_bot_config = CopyBotConfig()
high_prob_config = HighProbBotConfig()
