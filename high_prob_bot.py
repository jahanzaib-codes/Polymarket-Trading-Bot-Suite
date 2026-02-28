"""
Bot 2: Polymarket High-Probability Entry Bot
Scans all active markets and automatically enters positions when any market
side reaches the configurable threshold (default 0.90 / 90 cents).
Capitalizes on potential mean-reversion when probabilities are extreme.
"""
import logging
import time
import threading
from datetime import datetime, date
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, field

from polymarket_client import PolymarketClient
from config import HighProbBotConfig

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class HighProbPosition:
    """Represents an open high-probability position."""
    market_id: str
    token_id: str
    market_question: str
    side: str                   # "YES" or "NO" (mean-reversion side)
    trigger_price: float        # Price that triggered entry
    entry_price: float          # Actual fill price
    size_usdc: float
    opened_at: datetime = field(default_factory=datetime.now)
    current_price: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 1.0
    order_id: str = ""

    @property
    def pnl_usdc(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.current_price - self.entry_price) * (self.size_usdc / self.entry_price)

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100


@dataclass
class ScanRecord:
    """Log entry for a scanned market event."""
    timestamp: datetime
    market_question: str
    token_id: str
    detected_price: float
    action: str          # "ENTERED" | "SKIPPED" | "ALREADY_OPEN" | "RISK_BLOCKED"
    side: str
    size_usdc: float
    reason: str = ""


class HighProbRiskManager:
    """Risk management for the High-Probability bot."""

    def __init__(self, cfg: HighProbBotConfig):
        self.cfg = cfg
        self._daily_loss: float = 0.0
        self._weekly_loss: float = 0.0
        self._last_reset_day: date = date.today()
        self._last_reset_week: int = date.today().isocalendar()[1]

    def _reset_if_needed(self):
        today = date.today()
        if today != self._last_reset_day:
            self._daily_loss = 0.0
            self._last_reset_day = today
        week = today.isocalendar()[1]
        if week != self._last_reset_week:
            self._weekly_loss = 0.0
            self._last_reset_week = week

    def record_loss(self, amount: float):
        self._reset_if_needed()
        if amount > 0:
            self._daily_loss += amount
            self._weekly_loss += amount

    def can_enter(self, open_positions: int) -> tuple[bool, str]:
        self._reset_if_needed()
        cfg = self.cfg
        if cfg.EMERGENCY_STOP:
            return False, "Emergency stop is active"
        if self._daily_loss >= cfg.DAILY_LOSS_LIMIT_USDC:
            return False, f"Daily loss limit hit (${self._daily_loss:.2f})"
        if self._weekly_loss >= cfg.WEEKLY_LOSS_LIMIT_USDC:
            return False, f"Weekly loss limit hit (${self._weekly_loss:.2f})"
        if open_positions >= cfg.MAX_OPEN_POSITIONS:
            return False, f"Max positions reached ({open_positions})"
        return True, ""

    @property
    def daily_loss(self) -> float:
        self._reset_if_needed()
        return self._daily_loss

    @property
    def weekly_loss(self) -> float:
        self._reset_if_needed()
        return self._weekly_loss


class HighProbBot:
    """
    High-Probability Entry Bot
    ─────────────────────────
    Continuously scans every active Polymarket event.
    When any YES/NO token reaches >= threshold (default 0.90),
    it optionally enters the *opposing* side (mean-reversion play)
    or the high-probability side itself (momentum play).
    """

    def __init__(self, client: PolymarketClient, cfg: HighProbBotConfig):
        self.client = client
        self.cfg = cfg
        self.risk = HighProbRiskManager(cfg)
        self.running = False
        self._thread: Optional[threading.Thread] = None

        # State
        self.open_positions: Dict[str, HighProbPosition] = {}   # token_id -> position
        self.scan_log: List[ScanRecord] = []
        self.already_entered: set = set()   # token_ids we've entered to avoid duplicates
        self.stats = {
            "markets_scanned": 0,
            "entries": 0,
            "skipped": 0,
            "exits": 0,
            "total_pnl": 0.0,
            "stop_losses": 0,
            "take_profits": 0,
        }

        # GUI callbacks
        self.on_status_update: Optional[Callable[[str], None]] = None
        self.on_signal: Optional[Callable[[ScanRecord], None]] = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._emit("High-Probability Bot started – scanning markets…")

    def stop(self):
        self.running = False
        self._emit("High-Probability Bot stopped.")

    def emergency_stop(self):
        self.cfg.EMERGENCY_STOP = True
        self.stop()
        self._emit("⚠️  EMERGENCY STOP triggered – all trading halted.")

    # ─── Main loop ────────────────────────────────────────────────────────────

    def _run_loop(self):
        while self.running:
            try:
                self._scan_markets()
                self._update_positions()
                self._check_exits()
            except Exception as e:
                logger.error("High-prob bot loop error: %s", e)
                self._emit(f"Loop error: {e}")
            time.sleep(self.cfg.SCAN_INTERVAL_SECONDS)

    def _scan_markets(self):
        """Fetch all active markets and check prices against threshold."""
        markets = self.client.get_markets(limit=200, active_only=self.cfg.ACTIVE_MARKETS_ONLY)
        self.stats["markets_scanned"] += len(markets)

        for market in markets:
            if not self.running:
                break
            self._check_market(market)

    def _check_market(self, market: Dict):
        """Evaluate a single market for entry signals.

        Gamma API fields used:
          clobTokenIds  : [yes_token_id_str, no_token_id_str]
          outcomePrices : ["0.97", "0.03"]  (strings)
          outcomes      : ["Yes", "No"]     (strings)
          volumeNum     : float
          liquidityNum  : float
        """
        # Safety guard – skip any non-dict item that slipped through
        if not isinstance(market, dict):
            return

        question  = market.get("question", "Unknown")
        volume    = float(market.get("volumeNum")    or market.get("volume24hr")   or market.get("volume")    or 0)
        liquidity = float(market.get("liquidityNum") or market.get("liquidityTotal") or market.get("liquidity") or 0)

        # Liquidity / volume filters
        if self.cfg.MIN_VOLUME_USDC > 0 and volume < self.cfg.MIN_VOLUME_USDC:
            return
        if self.cfg.MIN_LIQUIDITY_USDC > 0 and liquidity < self.cfg.MIN_LIQUIDITY_USDC:
            return

        # ── Build a list of (token_id, outcome_label, price) tuples ─────────
        # Gamma API gives parallel arrays: clobTokenIds, outcomes, outcomePrices
        clob_ids       = market.get("clobTokenIds", [])     # e.g. ["123abc", "456def"]
        outcome_labels = market.get("outcomes", [])           # e.g. ["Yes", "No"]
        outcome_prices = market.get("outcomePrices", [])      # e.g. ["0.97", "0.03"]

        # Zip them together; skip if no token IDs available
        tokens = []
        for i, tid in enumerate(clob_ids):
            if not isinstance(tid, str) or not tid:
                continue
            label = outcome_labels[i] if i < len(outcome_labels) else ("YES" if i == 0 else "NO")
            # Use embedded outcomePrices first (saves a CLOB API call per token)
            embedded_price = None
            if i < len(outcome_prices):
                try:
                    embedded_price = float(outcome_prices[i])
                except (ValueError, TypeError):
                    pass
            tokens.append({"token_id": tid, "outcome": label.upper(), "embedded_price": embedded_price})

        for token in tokens:
            token_id       = token["token_id"]
            outcome        = token["outcome"]
            embedded_price = token["embedded_price"]

            # Already entered this token?
            if token_id in self.already_entered:
                continue

            # Use the embedded price from Gamma first; only hit CLOB if missing
            if embedded_price is not None:
                price = embedded_price
            else:
                price = self.client.get_midpoint(token_id)
                if price is None:
                    price = self.client.get_price(token_id, "BUY")
            if price is None:
                continue

            # Check threshold
            if price >= self.cfg.ENTRY_THRESHOLD:
                self._handle_signal(market, token_id, outcome, price, question)

    def _handle_signal(self, market: Dict, token_id: str, outcome: str, trigger_price: float, question: str):
        """Process a detected high-probability signal."""
        allowed, reason = self.risk.can_enter(len(self.open_positions))

        # Determine trading side
        if self.cfg.MEAN_REVERSION_MODE:
            # Enter the OPPOSITE side (bet it will mean-revert away from 90%+)
            trade_outcome = "NO" if outcome == "YES" else "YES"
            # The opposing token price is approx 1 - trigger_price
            trade_token = self._get_opposite_token(market, token_id)
            trade_price = round(1.0 - trigger_price, 4)
        else:
            # Enter the high-prob side directly (momentum)
            trade_outcome = outcome
            trade_token = token_id
            trade_price = trigger_price

        size = min(self.cfg.DEFAULT_POSITION_SIZE_USDC, self.cfg.MAX_POSITION_SIZE_USDC)

        action = "ENTERED" if allowed else "RISK_BLOCKED"
        record = ScanRecord(
            timestamp=datetime.now(),
            market_question=question,
            token_id=trade_token or token_id,
            detected_price=trigger_price,
            action=action,
            side=trade_outcome,
            size_usdc=size if allowed else 0.0,
            reason=reason if not allowed else (
                f"{'Mean-reversion' if self.cfg.MEAN_REVERSION_MODE else 'Momentum'} entry @ ≥${self.cfg.ENTRY_THRESHOLD:.2f}"
            ),
        )

        if allowed and trade_token:
            self._execute_entry(market, trade_token, trade_outcome, trade_price, size, question, record)
        elif not allowed:
            self.stats["skipped"] += 1

        self.scan_log.append(record)
        if self.on_signal:
            self.on_signal(record)

    def _execute_entry(
        self, market: Dict, token_id: str, outcome: str,
        price: float, size: float, question: str, record: ScanRecord,
    ):
        """Place the actual order."""
        result = None
        if self.client.connected:
            result = self.client.place_market_order(token_id, "BUY", size)

        success = result is not None or not self.client.connected

        if success:
            sl_price = price * (1 - self.cfg.STOP_LOSS_PCT / 100)
            tp_price = min(price * (1 + self.cfg.TAKE_PROFIT_PCT / 100), 0.99)

            pos = HighProbPosition(
                market_id=market.get("id") or market.get("conditionId", ""),
                token_id=token_id,
                market_question=question,
                side=outcome,
                trigger_price=record.detected_price,
                entry_price=price,
                size_usdc=size,
                current_price=price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                order_id=str(result.get("orderID", "")) if result else "paper",
            )
            self.open_positions[token_id] = pos
            self.already_entered.add(token_id)
            self.stats["entries"] += 1
            record.action = "ENTERED"
            self._emit(
                f"✅ ENTERED: {question[:45]} | {outcome} @ ${price:.3f} | SL:${sl_price:.3f} TP:${tp_price:.3f}"
            )
        else:
            record.action = "SKIPPED"
            record.reason = "Order placement failed"
            self._emit(f"❌ Failed to place order for: {question[:45]}")

    def _get_opposite_token(self, market: Dict, token_id: str) -> Optional[str]:
        """Find the opposing token ID (YES<->NO) using the clobTokenIds parallel array."""
        if not isinstance(market, dict):
            return None
        clob_ids = market.get("clobTokenIds", [])
        for tid in clob_ids:
            if isinstance(tid, str) and tid and tid != token_id:
                return tid
        return None

    def _update_positions(self):
        """Update current prices for all open positions."""
        for token_id, pos in list(self.open_positions.items()):
            price = self.client.get_midpoint(token_id)
            if price is not None:
                pos.current_price = price

    def _check_exits(self):
        """Check stop-loss and take-profit conditions."""
        for token_id, pos in list(self.open_positions.items()):
            exit_reason = None

            if pos.current_price <= pos.stop_loss_price:
                exit_reason = f"Stop-loss at ${pos.stop_loss_price:.3f}"
                self.stats["stop_losses"] += 1
                loss = abs(pos.pnl_usdc)
                self.risk.record_loss(loss)

            elif pos.current_price >= pos.take_profit_price:
                exit_reason = f"Take-profit at ${pos.take_profit_price:.3f}"
                self.stats["take_profits"] += 1

            if exit_reason:
                self.stats["exits"] += 1
                self.stats["total_pnl"] += pos.pnl_usdc

                record = ScanRecord(
                    timestamp=datetime.now(),
                    market_question=pos.market_question,
                    token_id=token_id,
                    detected_price=pos.current_price,
                    action="EXIT",
                    side="SELL",
                    size_usdc=pos.size_usdc,
                    reason=exit_reason,
                )
                self.scan_log.append(record)
                if self.on_signal:
                    self.on_signal(record)

                del self.open_positions[token_id]
                self._emit(f"🔒 Exit: {pos.market_question[:40]} | PnL: ${pos.pnl_usdc:.2f} | {exit_reason}")

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _emit(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        logger.info(full)
        if self.on_status_update:
            self.on_status_update(full)

    def get_summary(self) -> Dict:
        return {
            "running": self.running,
            "threshold": self.cfg.ENTRY_THRESHOLD,
            "mode": "Mean Reversion" if self.cfg.MEAN_REVERSION_MODE else "Momentum",
            "markets_scanned": self.stats["markets_scanned"],
            "open_positions": len(self.open_positions),
            "entries": self.stats["entries"],
            "exits": self.stats["exits"],
            "stop_losses": self.stats["stop_losses"],
            "take_profits": self.stats["take_profits"],
            "total_pnl": round(self.stats["total_pnl"], 4),
            "daily_loss": round(self.risk.daily_loss, 4),
            "weekly_loss": round(self.risk.weekly_loss, 4),
            "emergency_stop": self.cfg.EMERGENCY_STOP,
        }
