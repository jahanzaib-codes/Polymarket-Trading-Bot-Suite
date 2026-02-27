import os
import json
import logging
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

from config import PolymarketConfig, CopyBotConfig, HighProbBotConfig
from polymarket_client import PolymarketClient, ping_polymarket
from copy_trading_bot import CopyTradingBot
from high_prob_bot import HighProbBot

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─── Global State ─────────────────────────────────────────────────────────────
pm_config    = PolymarketConfig()
copy_config  = CopyBotConfig()
hp_config    = HighProbBotConfig()
pm_client    = PolymarketClient()
copy_bot: CopyTradingBot = None
hp_bot: HighProbBot      = None


def _rebuild_bots():
    global copy_bot, hp_bot
    copy_bot = CopyTradingBot(pm_client, copy_config)
    hp_bot   = HighProbBot(pm_client, hp_config)

    def _copy_status(msg):
        socketio.emit("copy_log", {"message": msg})

    def _copy_trade(trade):
        socketio.emit("copy_trade", {
            "time":     trade.timestamp.strftime("%H:%M:%S"),
            "action":   trade.action,
            "market":   trade.market_question[:60],
            "side":     trade.side,
            "size":     f"${trade.our_size:.2f}",
            "price":    f"${trade.price:.3f}",
            "reason":   trade.reason,
        })

    def _hp_status(msg):
        socketio.emit("hp_log", {"message": msg})

    def _hp_signal(sig):
        socketio.emit("hp_signal", {
            "time":     sig.timestamp.strftime("%H:%M:%S"),
            "action":   sig.action,
            "market":   sig.market_question[:60],
            "side":     sig.side,
            "price":    f"${sig.detected_price:.3f}",
            "size":     f"${sig.size_usdc:.2f}",
            "reason":   sig.reason,
        })

    copy_bot.on_status_update = _copy_status
    copy_bot.on_trade         = _copy_trade
    hp_bot.on_status_update   = _hp_status
    hp_bot.on_signal          = _hp_signal


_rebuild_bots()


# ─── Background stats pusher ──────────────────────────────────────────────────
def _stats_pusher():
    while True:
        try:
            copy_sum = copy_bot.get_summary() if copy_bot else {}
            hp_sum   = hp_bot.get_summary()   if hp_bot else {}
            socketio.emit("stats_update", {"copy": copy_sum, "hp": hp_sum})
        except Exception:
            pass
        time.sleep(3)

threading.Thread(target=_stats_pusher, daemon=True).start()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


# ── Connectivity ──────────────────────────────────────────────────────────────

@app.route("/api/ping")
def api_ping():
    ok = ping_polymarket()
    return jsonify({"polymarket_reachable": ok})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    global pm_client
    data = request.json or {}
    pm_config.PRIVATE_KEY    = data.get("private_key", "")
    pm_config.API_KEY        = data.get("api_key", "")
    pm_config.API_SECRET     = data.get("api_secret", "")
    pm_config.API_PASSPHRASE = data.get("api_passphrase", "")
    pm_config.FUNDER_ADDRESS = data.get("funder_address", "")

    pm_client = PolymarketClient(
        private_key=pm_config.PRIVATE_KEY,
        api_key=pm_config.API_KEY,
        api_secret=pm_config.API_SECRET,
        api_passphrase=pm_config.API_PASSPHRASE,
        funder_address=pm_config.FUNDER_ADDRESS,
    )
    connected = pm_client.connect()
    _rebuild_bots()
    return jsonify({"connected": connected})


@app.route("/api/balance")
def api_balance():
    bal = pm_client.get_my_balance()
    return jsonify({"balance_usdc": bal})


# ── Copy Bot API ──────────────────────────────────────────────────────────────

@app.route("/api/copy/config", methods=["GET", "POST"])
def api_copy_config():
    global copy_config
    if request.method == "POST":
        d = request.json or {}
        copy_config.TARGET_TRADER_ADDRESS    = d.get("target_address",       copy_config.TARGET_TRADER_ADDRESS)
        copy_config.TOTAL_CAPITAL_USDC       = float(d.get("total_capital",  copy_config.TOTAL_CAPITAL_USDC))
        copy_config.CAPITAL_ALLOCATION_PCT   = float(d.get("capital_alloc",  copy_config.CAPITAL_ALLOCATION_PCT))
        copy_config.MAX_TRADE_SIZE_USDC      = float(d.get("max_trade",      copy_config.MAX_TRADE_SIZE_USDC))
        copy_config.MIN_TRADE_SIZE_USDC      = float(d.get("min_trade",      copy_config.MIN_TRADE_SIZE_USDC))
        copy_config.MAX_RISK_PER_TRADE_PCT   = float(d.get("max_risk_pct",   copy_config.MAX_RISK_PER_TRADE_PCT))
        copy_config.STOP_LOSS_PCT            = float(d.get("stop_loss_pct",  copy_config.STOP_LOSS_PCT))
        copy_config.DAILY_LOSS_LIMIT_USDC    = float(d.get("daily_limit",    copy_config.DAILY_LOSS_LIMIT_USDC))
        copy_config.WEEKLY_LOSS_LIMIT_USDC   = float(d.get("weekly_limit",   copy_config.WEEKLY_LOSS_LIMIT_USDC))
        copy_config.MAX_OPEN_POSITIONS       = int(d.get("max_positions",    copy_config.MAX_OPEN_POSITIONS))
        copy_config.COPY_RATIO               = float(d.get("copy_ratio",     copy_config.COPY_RATIO))
        copy_config.POLL_INTERVAL_SECONDS    = float(d.get("poll_interval",  copy_config.POLL_INTERVAL_SECONDS))
        copy_config.PROPORTIONAL_SIZING      = bool(d.get("proportional",    copy_config.PROPORTIONAL_SIZING))
        _rebuild_bots()
        return jsonify({"status": "ok"})
    return jsonify(copy_config.__dict__)


@app.route("/api/copy/start", methods=["POST"])
def api_copy_start():
    if copy_bot and not copy_bot.running:
        copy_bot.start()
    return jsonify({"running": copy_bot.running if copy_bot else False})


@app.route("/api/copy/stop", methods=["POST"])
def api_copy_stop():
    if copy_bot:
        copy_bot.stop()
    return jsonify({"running": False})


@app.route("/api/copy/emergency", methods=["POST"])
def api_copy_emergency():
    if copy_bot:
        copy_bot.emergency_stop()
    return jsonify({"emergency_stop": True})


@app.route("/api/copy/positions")
def api_copy_positions():
    if not copy_bot:
        return jsonify([])
    positions = []
    for pos in copy_bot.open_positions.values():
        positions.append({
            "market":      pos.market_question[:60],
            "side":        pos.side,
            "entry":       round(pos.entry_price, 4),
            "current":     round(pos.current_price, 4),
            "size":        round(pos.size_usdc, 2),
            "pnl":         round(pos.pnl_usdc, 4),
            "pnl_pct":     round(pos.pnl_pct, 2),
            "stop_loss":   round(pos.stop_loss_price, 4),
            "opened_at":   pos.opened_at.strftime("%H:%M:%S"),
        })
    return jsonify(positions)


@app.route("/api/copy/log")
def api_copy_log():
    if not copy_bot:
        return jsonify([])
    log = []
    for r in reversed(copy_bot.trade_log[-100:]):
        log.append({
            "time":    r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "action":  r.action,
            "market":  r.market_question[:60],
            "side":    r.side,
            "our_size": round(r.our_size, 2),
            "price":   round(r.price, 4),
            "reason":  r.reason,
        })
    return jsonify(log)


# ── High-Prob Bot API ─────────────────────────────────────────────────────────

@app.route("/api/hp/config", methods=["GET", "POST"])
def api_hp_config():
    global hp_config
    if request.method == "POST":
        d = request.json or {}
        hp_config.ENTRY_THRESHOLD          = float(d.get("threshold",      hp_config.ENTRY_THRESHOLD))
        hp_config.DEFAULT_POSITION_SIZE_USDC = float(d.get("pos_size",    hp_config.DEFAULT_POSITION_SIZE_USDC))
        hp_config.MAX_POSITION_SIZE_USDC   = float(d.get("max_pos_size",   hp_config.MAX_POSITION_SIZE_USDC))
        hp_config.STOP_LOSS_PCT            = float(d.get("stop_loss_pct",  hp_config.STOP_LOSS_PCT))
        hp_config.TAKE_PROFIT_PCT          = float(d.get("take_profit_pct",hp_config.TAKE_PROFIT_PCT))
        hp_config.DAILY_LOSS_LIMIT_USDC    = float(d.get("daily_limit",    hp_config.DAILY_LOSS_LIMIT_USDC))
        hp_config.WEEKLY_LOSS_LIMIT_USDC   = float(d.get("weekly_limit",   hp_config.WEEKLY_LOSS_LIMIT_USDC))
        hp_config.MAX_OPEN_POSITIONS       = int(d.get("max_positions",    hp_config.MAX_OPEN_POSITIONS))
        hp_config.MIN_LIQUIDITY_USDC       = float(d.get("min_liquidity",  hp_config.MIN_LIQUIDITY_USDC))
        hp_config.MIN_VOLUME_USDC          = float(d.get("min_volume",     hp_config.MIN_VOLUME_USDC))
        hp_config.SCAN_INTERVAL_SECONDS    = float(d.get("scan_interval",  hp_config.SCAN_INTERVAL_SECONDS))
        hp_config.MEAN_REVERSION_MODE      = bool(d.get("mean_reversion",  hp_config.MEAN_REVERSION_MODE))
        _rebuild_bots()
        return jsonify({"status": "ok"})
    return jsonify(hp_config.__dict__)


@app.route("/api/hp/start", methods=["POST"])
def api_hp_start():
    if hp_bot and not hp_bot.running:
        hp_bot.start()
    return jsonify({"running": hp_bot.running if hp_bot else False})


@app.route("/api/hp/stop", methods=["POST"])
def api_hp_stop():
    if hp_bot:
        hp_bot.stop()
    return jsonify({"running": False})


@app.route("/api/hp/emergency", methods=["POST"])
def api_hp_emergency():
    if hp_bot:
        hp_bot.emergency_stop()
    return jsonify({"emergency_stop": True})


@app.route("/api/hp/positions")
def api_hp_positions():
    if not hp_bot:
        return jsonify([])
    positions = []
    for pos in hp_bot.open_positions.values():
        positions.append({
            "market":      pos.market_question[:60],
            "side":        pos.side,
            "trigger":     round(pos.trigger_price, 4),
            "entry":       round(pos.entry_price, 4),
            "current":     round(pos.current_price, 4),
            "size":        round(pos.size_usdc, 2),
            "pnl":         round(pos.pnl_usdc, 4),
            "pnl_pct":     round(pos.pnl_pct, 2),
            "stop_loss":   round(pos.stop_loss_price, 4),
            "take_profit": round(pos.take_profit_price, 4),
            "opened_at":   pos.opened_at.strftime("%H:%M:%S"),
        })
    return jsonify(positions)


@app.route("/api/hp/log")
def api_hp_log():
    if not hp_bot:
        return jsonify([])
    log = []
    for r in reversed(hp_bot.scan_log[-100:]):
        log.append({
            "time":    r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "action":  r.action,
            "market":  r.market_question[:60],
            "side":    r.side,
            "price":   round(r.detected_price, 4),
            "size":    round(r.size_usdc, 2),
            "reason":  r.reason,
        })
    return jsonify(log)


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Polymarket Trading Bots Dashboard")
    print("  Open: http://localhost:5000")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
