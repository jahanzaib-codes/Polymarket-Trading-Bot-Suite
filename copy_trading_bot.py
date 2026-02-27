"""
Bot 1: Polymarket Copy Trading Bot
Monitors a target trader's positions/trades in real-time and mirrors them
with proportional sizing and comprehensive risk management.
"""
import logging
import time
import threading
from datetime import datetime, date
from typing import Optional, Dict, List, Set, Callable
from dataclasses import dataclass, field

from polymarket_client import PolymarketClient
from config import CopyBotConfig

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents a mirrored position."""
    market_id: str
    token_id: str
    market_question: str
    side: str
    entry_price: float
    size_usdc: float
    opened_at: datetime = field(default_factory=datetime.now)
    current_price: float = 0.0
    pnl_usdc: float = 0.0
    stop_loss_price: float = 0.0
    order_id: str = ""

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100


@dataclass
class TradeRecord:
    """Audit log entry for a trade."""
    timestamp: datetime
    action: str          # "COPY_BUY" | "COPY_SELL" | "STOP_LOSS" | "EMERGENCY_STOP" | "SKIPPED"
    market_id: str
    market_question: str
    side: str
    target_address: str
    original_size: float
    our_size: float
    price: float
    reason: str = ""


class RiskManager:
    """Centralised risk gating logic."""

    def __init__(self, cfg: CopyBotConfig):
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

    def can_trade(self, proposed_size: float, open_positions: int) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        self._reset_if_needed()
        cfg = self.cfg
        if cfg.EMERGENCY_STOP:
            return False, "Emergency stop is active"
        if self._daily_loss >= cfg.DAILY_LOSS_LIMIT_USDC:
            return False, f"Daily loss limit hit (${self._daily_loss:.2f})"
        if self._weekly_loss >= cfg.WEEKLY_LOSS_LIMIT_USDC:
            return False, f"Weekly loss limit hit (${self._weekly_loss:.2f})"
        if open_positions >= cfg.MAX_OPEN_POSITIONS:
            return False, f"Max open positions reached ({open_positions})"
        if proposed_size < cfg.MIN_TRADE_SIZE_USDC:
            return False, f"Trade too small (${proposed_size:.2f} < min ${cfg.MIN_TRADE_SIZE_USDC})"
        return True, ""

    def calculate_size(self, target_size: float, available_capital: float) -> float:
        """Compute proportional size capped by risk rules."""
        cfg = self.cfg
        if cfg.PROPORTIONAL_SIZING:
            size = target_size * cfg.COPY_RATIO
        else:
            size = (available_capital * cfg.CAPITAL_ALLOCATION_PCT / 100)
        size = min(size, cfg.MAX_TRADE_SIZE_USDC)
        size = min(size, available_capital * cfg.MAX_RISK_PER_TRADE_PCT / 100)
        size = min(size, available_capital)
        return round(size, 2)

    @property
    def daily_loss(self) -> float:
        self._reset_if_needed()
        return self._daily_loss

    @property
    def weekly_loss(self) -> float:
        self._reset_if_needed()
        return self._weekly_loss


class CopyTradingBot:
    """
    Polymarket Copy Trading Bot – mirrors trades from a designated address.
    """

    def __init__(self, client: PolymarketClient, cfg: CopyBotConfig):
        self.client = client
        self.cfg = cfg
        self.risk = RiskManager(cfg)
        self.running = False
        self._thread: Optional[threading.Thread] = None

        # State
        self.open_positions: Dict[str, Position] = {}   # token_id -> Position
        self.trade_log: List[TradeRecord] = []
        self.known_trade_ids: Set[str] = set()          # IDs we've already processed
        self.last_target_positions: Dict[str, Dict] = {}
        self.stats = {
            "trades_copied": 0,
            "trades_skipped": 0,
            "total_pnl": 0.0,
            "stop_losses_triggered": 0,
        }

        # Callbacks for GUI updates
        self.on_status_update: Optional[Callable[[str], None]] = None
        self.on_trade: Optional[Callable[[TradeRecord], None]] = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        if self.running:
            return
        if not self.cfg.TARGET_TRADER_ADDRESS:
            self._emit("ERROR: Target trader address not configured.")
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._emit(f"Copy Trading Bot started – tracking {self.cfg.TARGET_TRADER_ADDRESS[:10]}…")

    def stop(self):
        self.running = False
        self._emit("Copy Trading Bot stopped.")

    def emergency_stop(self):
        self.cfg.EMERGENCY_STOP = True
        self.stop()
        self._emit("⚠️  EMERGENCY STOP triggered – all trading halted.")

    # ─── Main loop ────────────────────────────────────────────────────────────

    def _run_loop(self):
        while self.running:
            try:
                self._check_new_trades()
                self._update_open_positions()
                self._check_stop_losses()
            except Exception as e:
                logger.error("Copy bot loop error: %s", e)
                self._emit(f"Loop error: {e}")
            time.sleep(self.cfg.POLL_INTERVAL_SECONDS)

    def _check_new_trades(self):
        """Fetch target trader's recent trades and copy any new ones."""
        target = self.cfg.TARGET_TRADER_ADDRESS
        trades = self.client.get_trader_trades(target, limit=20)
        if not trades:
            return

        # Build current position snapshot for change detection
        current_positions = {
            p.get("conditionId") or p.get("market_id", ""): p
            for p in self.client.get_trader_positions(target)
        }

        for trade in trades:
            trade_id = trade.get("id") or trade.get("transactionHash", "")
            if trade_id in self.known_trade_ids:
                continue
            self.known_trade_ids.add(trade_id)

            # Parse trade fields (field names vary across API versions)
            token_id    = trade.get("asset") or trade.get("token_id") or trade.get("conditionId", "")
            side        = (trade.get("side") or trade.get("type") or "BUY").upper()
            price_raw   = trade.get("price") or trade.get("usdcSize", 0)
            size_raw    = trade.get("usdcSize") or trade.get("size") or trade.get("amount", 0)
            question    = trade.get("market", {}).get("question", "") if isinstance(trade.get("market"), dict) else trade.get("marketQuestion", "Unknown")

            try:
                price = float(price_raw)
                target_size = float(size_raw)
            except (ValueError, TypeError):
                continue

            if price <= 0 or target_size <= 0 or not token_id:
                continue

            # Only replicate BUY trades for now (SELL = exit handled by stop-loss)
            if "BUY" not in side and "ENTER" not in side:
                continue

            # Risk check
            available = self.client.get_my_balance() if self.client.connected else self.cfg.TOTAL_CAPITAL_USDC
            our_size = self.risk.calculate_size(target_size, available)
            allowed, reason = self.risk.can_trade(our_size, len(self.open_positions))

            record = TradeRecord(
                timestamp=datetime.now(),
                action="COPY_BUY" if allowed else "SKIPPED",
                market_id=token_id,
                market_question=question,
                side=side,
                target_address=target,
                original_size=target_size,
                our_size=our_size,
                price=price,
                reason=reason if not allowed else "Copied from target trader",
            )

            if allowed:
                self._execute_copy_trade(token_id, side, price, our_size, question, record)
            else:
                self.stats["trades_skipped"] += 1
                self._emit(f"Trade skipped: {question[:40]} – {reason}")

            self.trade_log.append(record)
            if self.on_trade:
                self.on_trade(record)

    def _execute_copy_trade(
        self, token_id: str, side: str, price: float,
        size_usdc: float, question: str, record: TradeRecord,
    ):
        """Place actual copy trade order."""
        result = None
        if self.client.connected:
            result = self.client.place_market_order(token_id, side, size_usdc)

        success = result is not None or not self.client.connected  # allow paper-trading

        if success:
            stop_price = price * (1 - self.cfg.STOP_LOSS_PCT / 100) if side == "BUY" else price * (1 + self.cfg.STOP_LOSS_PCT / 100)
            pos = Position(
                market_id=token_id,
                token_id=token_id,
                market_question=question,
                side=side,
                entry_price=price,
                size_usdc=size_usdc,
                current_price=price,
                stop_loss_price=stop_price,
                order_id=str(result.get("orderID", "")) if result else "paper",
            )
            self.open_positions[token_id] = pos
            self.stats["trades_copied"] += 1
            record.action = "COPY_BUY"
            self._emit(f"✅ Copied trade: {question[:40]} | ${size_usdc:.2f} @ ${price:.3f}")
        else:
            record.reason = "Order placement failed"
            self._emit(f"❌ Failed to place order for: {question[:40]}")

    def _update_open_positions(self):
        """Refresh current prices for open positions."""
        for tid, pos in list(self.open_positions.items()):
            price = self.client.get_midpoint(tid)
            if price is not None:
                pos.current_price = price
                pos.pnl_usdc = (price - pos.entry_price) * (pos.size_usdc / pos.entry_price) if pos.entry_price > 0 else 0.0

    def _check_stop_losses(self):
        """Trigger stop-loss for positions that have breached threshold."""
        for tid, pos in list(self.open_positions.items()):
            triggered = False
            if pos.side == "BUY" and pos.current_price <= pos.stop_loss_price:
                triggered = True
            elif pos.side == "SELL" and pos.current_price >= pos.stop_loss_price:
                triggered = True

            if triggered:
                loss = abs(pos.pnl_usdc)
                self.risk.record_loss(loss)
                self.stats["stop_losses_triggered"] += 1
                self.stats["total_pnl"] += pos.pnl_usdc

                record = TradeRecord(
                    timestamp=datetime.now(),
                    action="STOP_LOSS",
                    market_id=tid,
                    market_question=pos.market_question,
                    side="SELL" if pos.side == "BUY" else "BUY",
                    target_address=self.cfg.TARGET_TRADER_ADDRESS,
                    original_size=pos.size_usdc,
                    our_size=pos.size_usdc,
                    price=pos.current_price,
                    reason=f"Stop-loss at ${pos.stop_loss_price:.3f}",
                )
                self.trade_log.append(record)
                del self.open_positions[tid]
                self._emit(f"🛑 Stop-loss: {pos.market_question[:40]} | Loss: ${loss:.2f}")
                if self.on_trade:
                    self.on_trade(record)

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
            "target": self.cfg.TARGET_TRADER_ADDRESS,
            "open_positions": len(self.open_positions),
            "trades_copied": self.stats["trades_copied"],
            "trades_skipped": self.stats["trades_skipped"],
            "stop_losses": self.stats["stop_losses_triggered"],
            "total_pnl": round(self.stats["total_pnl"], 4),
            "daily_loss": round(self.risk.daily_loss, 4),
            "weekly_loss": round(self.risk.weekly_loss, 4),
            "emergency_stop": self.cfg.EMERGENCY_STOP,
        }
