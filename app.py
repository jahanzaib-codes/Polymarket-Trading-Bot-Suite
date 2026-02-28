"""
Polymarket Trading Bots – Web Dashboard (Flask + SocketIO)
Features:
  - Credential persistence (saved to credentials.json, never to GitHub)
  - Optional dashboard password protection
  - REST API for both bots
  - Real-time stat pushing via WebSocket
"""
import os
import json
import logging
import threading
import time
import secrets
from datetime import datetime
from functools import wraps

# Load .env file if present (VPS password config, never committed to git)
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)   # does NOT override vars already set in shell
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO

from config import PolymarketConfig, CopyBotConfig, HighProbBotConfig, DashboardConfig
from polymarket_client import PolymarketClient, ping_polymarket
from copy_trading_bot import CopyTradingBot
from high_prob_bot import HighProbBot

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Credential persistence helpers ───────────────────────────────────────────
CREDS_FILE      = "credentials.json"
BOT_CONFIG_FILE = "bot_config.json"    # Persists Copy Bot + HP Bot settings

def _load_credentials() -> dict:
    """Load saved credentials from local JSON file."""
    try:
        if os.path.exists(CREDS_FILE):
            with open(CREDS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("Could not load credentials file: %s", e)
    return {}

def _save_credentials(data: dict):
    """Persist credentials to local JSON file (never committed to git)."""
    try:
        with open(CREDS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Credentials saved to %s", CREDS_FILE)
    except Exception as e:
        logger.error("Could not save credentials: %s", e)

def _load_bot_config():
    """Load saved bot configuration from disk and apply to copy_config / hp_config."""
    global copy_config, hp_config
    try:
        if os.path.exists(BOT_CONFIG_FILE):
            with open(BOT_CONFIG_FILE, "r") as f:
                saved = json.load(f)
            # ── Copy Bot ──
            cc = saved.get("copy", {})
            for k, v in cc.items():
                if hasattr(copy_config, k):
                    setattr(copy_config, k, type(getattr(copy_config, k))(v))
            # ── HP Bot ──
            hc = saved.get("hp", {})
            for k, v in hc.items():
                if hasattr(hp_config, k):
                    setattr(hp_config, k, type(getattr(hp_config, k))(v))
            logger.info("Bot config loaded from %s", BOT_CONFIG_FILE)
    except Exception as e:
        logger.warning("Could not load bot config: %s", e)

def _save_bot_config():
    """Persist current bot config to disk so it survives restarts."""
    try:
        data = {
            "copy": {k: v for k, v in copy_config.__dict__.items() if not k.startswith("_")},
            "hp":   {k: v for k, v in hp_config.__dict__.items()   if not k.startswith("_")},
        }
        with open(BOT_CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Bot config saved to %s", BOT_CONFIG_FILE)
    except Exception as e:
        logger.error("Could not save bot config: %s", e)

# ─── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─── Dashboard config ─────────────────────────────────────────────────────────
dash_config = DashboardConfig()
# Read password settings from environment variables (VPS-safe)
dash_config.PASSWORD_ENABLED  = os.environ.get("DASH_PASSWORD_ENABLED", "false").lower() == "true"
dash_config.DASHBOARD_PASSWORD = os.environ.get("DASH_PASSWORD", "changeme123")

# ─── Global State ─────────────────────────────────────────────────────────────
pm_config   = PolymarketConfig()
copy_config = CopyBotConfig()
hp_config   = HighProbBotConfig()
pm_client   = PolymarketClient()
copy_bot: CopyTradingBot = None
hp_bot: HighProbBot      = None

# Auto-load saved credentials + bot config on startup
_saved = _load_credentials()
if _saved:
    pm_config.PRIVATE_KEY    = _saved.get("private_key", "")
    pm_config.API_KEY        = _saved.get("api_key", "")
    pm_config.API_SECRET     = _saved.get("api_secret", "")
    pm_config.API_PASSPHRASE = _saved.get("api_passphrase", "")
    pm_config.FUNDER_ADDRESS = _saved.get("funder_address", "")
    if pm_config.PRIVATE_KEY:
        pm_client = PolymarketClient(
            private_key=pm_config.PRIVATE_KEY,
            api_key=pm_config.API_KEY,
            api_secret=pm_config.API_SECRET,
            api_passphrase=pm_config.API_PASSPHRASE,
            funder_address=pm_config.FUNDER_ADDRESS,
        )
        pm_client.connect()
        logger.info("Auto-connected using saved credentials.")

_load_bot_config()   # Restore Copy Bot + HP Bot settings from disk

# ─── Password auth decorator ──────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if dash_config.PASSWORD_ENABLED and not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─── Bot builder ──────────────────────────────────────────────────────────────
def _rebuild_bots():
    global copy_bot, hp_bot
    copy_bot = CopyTradingBot(pm_client, copy_config)
    hp_bot   = HighProbBot(pm_client, hp_config)

    def _copy_status(msg):
        socketio.emit("copy_log", {"message": msg})

    def _copy_trade(trade):
        socketio.emit("copy_trade", {
            "time":    trade.timestamp.strftime("%H:%M:%S"),
            "action":  trade.action,
            "market":  trade.market_question[:60],
            "side":    trade.side,
            "size":    f"${trade.our_size:.2f}",
            "price":   f"${trade.price:.3f}",
            "reason":  trade.reason,
        })

    def _hp_status(msg):
        socketio.emit("hp_log", {"message": msg})

    def _hp_signal(sig):
        socketio.emit("hp_signal", {
            "time":    sig.timestamp.strftime("%H:%M:%S"),
            "action":  sig.action,
            "market":  sig.market_question[:60],
            "side":    sig.side,
            "price":   f"${sig.detected_price:.3f}",
            "size":    f"${sig.size_usdc:.2f}",
            "reason":  sig.reason,
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

# ─── Auth Routes ──────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == dash_config.DASHBOARD_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "❌ Incorrect password. Try again."
    return render_template("login.html", error=error, enabled=dash_config.PASSWORD_ENABLED)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── Main Routes ──────────────────────────────────────────────────────────────
@app.route("/")
@require_auth
def index():
    return render_template("dashboard.html")

# ─── Connectivity ─────────────────────────────────────────────────────────────
@app.route("/api/ping")
def api_ping():
    ok = ping_polymarket()
    return jsonify({"polymarket_reachable": ok})

@app.route("/api/credentials/load")
@require_auth
def api_credentials_load():
    """Return saved credentials (masked for display)."""
    saved = _load_credentials()
    return jsonify({
        "has_private_key":    bool(saved.get("private_key")),
        "api_key":            saved.get("api_key", ""),
        "funder_address":     saved.get("funder_address", ""),
        "has_api_secret":     bool(saved.get("api_secret")),
        "has_api_passphrase": bool(saved.get("api_passphrase")),
    })

@app.route("/api/connect", methods=["POST"])
@require_auth
def api_connect():
    global pm_client
    data = request.json or {}
    pm_config.PRIVATE_KEY    = data.get("private_key", "")
    pm_config.API_KEY        = data.get("api_key", "")
    pm_config.API_SECRET     = data.get("api_secret", "")
    pm_config.API_PASSPHRASE = data.get("api_passphrase", "")
    pm_config.FUNDER_ADDRESS = data.get("funder_address", "")

    # Persist credentials to disk so they survive server restarts
    _save_credentials({
        "private_key":    pm_config.PRIVATE_KEY,
        "api_key":        pm_config.API_KEY,
        "api_secret":     pm_config.API_SECRET,
        "api_passphrase": pm_config.API_PASSPHRASE,
        "funder_address": pm_config.FUNDER_ADDRESS,
    })

    pm_client = PolymarketClient(
        private_key=pm_config.PRIVATE_KEY,
        api_key=pm_config.API_KEY,
        api_secret=pm_config.API_SECRET,
        api_passphrase=pm_config.API_PASSPHRASE,
        funder_address=pm_config.FUNDER_ADDRESS,
    )
    connected = pm_client.connect()
    _rebuild_bots()
    return jsonify({"connected": connected, "saved": True})

@app.route("/api/balance")
@require_auth
def api_balance():
    bal = pm_client.get_my_balance()
    return jsonify({"balance_usdc": bal})

# ─── Security: change dashboard password ──────────────────────────────────────
@app.route("/api/security/password", methods=["POST"])
@require_auth
def api_set_password():
    d = request.json or {}
    new_pwd = d.get("password", "").strip()
    if len(new_pwd) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    dash_config.DASHBOARD_PASSWORD = new_pwd
    dash_config.PASSWORD_ENABLED   = True
    return jsonify({"status": "ok", "message": "Password updated. Restart server to apply on VPS."})

# ─── Copy Bot API ──────────────────────────────────────────────────────────────
@app.route("/api/copy/config", methods=["GET", "POST"])
@require_auth
def api_copy_config():
    global copy_config
    if request.method == "POST":
        d = request.json or {}
        copy_config.TARGET_TRADER_ADDRESS  = d.get("target_address",  copy_config.TARGET_TRADER_ADDRESS)
        copy_config.TOTAL_CAPITAL_USDC     = float(d.get("total_capital",  copy_config.TOTAL_CAPITAL_USDC))
        copy_config.CAPITAL_ALLOCATION_PCT = float(d.get("capital_alloc",  copy_config.CAPITAL_ALLOCATION_PCT))
        copy_config.MAX_TRADE_SIZE_USDC    = float(d.get("max_trade",      copy_config.MAX_TRADE_SIZE_USDC))
        copy_config.MIN_TRADE_SIZE_USDC    = float(d.get("min_trade",      copy_config.MIN_TRADE_SIZE_USDC))
        copy_config.MAX_RISK_PER_TRADE_PCT = float(d.get("max_risk_pct",   copy_config.MAX_RISK_PER_TRADE_PCT))
        copy_config.STOP_LOSS_PCT          = float(d.get("stop_loss_pct",  copy_config.STOP_LOSS_PCT))
        copy_config.DAILY_LOSS_LIMIT_USDC  = float(d.get("daily_limit",    copy_config.DAILY_LOSS_LIMIT_USDC))
        copy_config.WEEKLY_LOSS_LIMIT_USDC = float(d.get("weekly_limit",   copy_config.WEEKLY_LOSS_LIMIT_USDC))
        copy_config.MAX_OPEN_POSITIONS     = int(d.get("max_positions",    copy_config.MAX_OPEN_POSITIONS))
        copy_config.COPY_RATIO             = float(d.get("copy_ratio",     copy_config.COPY_RATIO))
        copy_config.POLL_INTERVAL_SECONDS  = float(d.get("poll_interval",  copy_config.POLL_INTERVAL_SECONDS))
        copy_config.PROPORTIONAL_SIZING    = bool(d.get("proportional",    copy_config.PROPORTIONAL_SIZING))
        _rebuild_bots()
        _save_bot_config()   # Persist to disk
        return jsonify({"status": "ok"})
    return jsonify(copy_config.__dict__)

@app.route("/api/copy/start",     methods=["POST"])
@require_auth
def api_copy_start():
    if copy_bot and not copy_bot.running:
        copy_bot.start()
    return jsonify({"running": copy_bot.running if copy_bot else False})

@app.route("/api/copy/stop",      methods=["POST"])
@require_auth
def api_copy_stop():
    if copy_bot: copy_bot.stop()
    return jsonify({"running": False})

@app.route("/api/copy/emergency", methods=["POST"])
@require_auth
def api_copy_emergency():
    if copy_bot: copy_bot.emergency_stop()
    return jsonify({"emergency_stop": True})

@app.route("/api/copy/positions")
@require_auth
def api_copy_positions():
    if not copy_bot:
        return jsonify([])
    return jsonify([{
        "market":    pos.market_question[:60],
        "side":      pos.side,
        "entry":     round(pos.entry_price, 4),
        "current":   round(pos.current_price, 4),
        "size":      round(pos.size_usdc, 2),
        "pnl":       round(pos.pnl_usdc, 4),
        "pnl_pct":   round(pos.pnl_pct, 2),
        "stop_loss": round(pos.stop_loss_price, 4),
        "opened_at": pos.opened_at.strftime("%H:%M:%S"),
    } for pos in copy_bot.open_positions.values()])

@app.route("/api/copy/log")
@require_auth
def api_copy_log():
    if not copy_bot:
        return jsonify([])
    return jsonify([{
        "time":     r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "action":   r.action,
        "market":   r.market_question[:60],
        "side":     r.side,
        "our_size": round(r.our_size, 2),
        "price":    round(r.price, 4),
        "reason":   r.reason,
    } for r in reversed(copy_bot.trade_log[-100:])])

# ─── High-Prob Bot API ─────────────────────────────────────────────────────────
@app.route("/api/hp/config", methods=["GET", "POST"])
@require_auth
def api_hp_config():
    global hp_config
    if request.method == "POST":
        d = request.json or {}
        hp_config.ENTRY_THRESHOLD_MIN        = float(d.get("threshold_min",    hp_config.ENTRY_THRESHOLD_MIN))
        hp_config.ENTRY_THRESHOLD_MAX        = float(d.get("threshold_max",    hp_config.ENTRY_THRESHOLD_MAX))
        hp_config.ORDER_TYPE                 = str(d.get("order_type",         hp_config.ORDER_TYPE)).upper()
        hp_config.DEFAULT_POSITION_SIZE_USDC = float(d.get("pos_size",        hp_config.DEFAULT_POSITION_SIZE_USDC))
        hp_config.MAX_POSITION_SIZE_USDC     = float(d.get("max_pos_size",    hp_config.MAX_POSITION_SIZE_USDC))
        hp_config.STOP_LOSS_PCT              = float(d.get("stop_loss_pct",   hp_config.STOP_LOSS_PCT))
        hp_config.TAKE_PROFIT_PCT            = float(d.get("take_profit_pct", hp_config.TAKE_PROFIT_PCT))
        hp_config.DAILY_LOSS_LIMIT_USDC      = float(d.get("daily_limit",     hp_config.DAILY_LOSS_LIMIT_USDC))
        hp_config.WEEKLY_LOSS_LIMIT_USDC     = float(d.get("weekly_limit",    hp_config.WEEKLY_LOSS_LIMIT_USDC))
        hp_config.MAX_OPEN_POSITIONS         = int(d.get("max_positions",     hp_config.MAX_OPEN_POSITIONS))
        hp_config.MIN_LIQUIDITY_USDC         = float(d.get("min_liquidity",   hp_config.MIN_LIQUIDITY_USDC))
        hp_config.MIN_VOLUME_USDC            = float(d.get("min_volume",      hp_config.MIN_VOLUME_USDC))
        hp_config.SCAN_INTERVAL_SECONDS      = float(d.get("scan_interval",   hp_config.SCAN_INTERVAL_SECONDS))
        hp_config.MEAN_REVERSION_MODE        = bool(d.get("mean_reversion",   hp_config.MEAN_REVERSION_MODE))
        hp_config.MAX_HOURS_TO_CLOSE         = float(d.get("max_hours",       hp_config.MAX_HOURS_TO_CLOSE))
        _rebuild_bots()
        _save_bot_config()   # Persist to disk
        return jsonify({"status": "ok"})
    return jsonify(hp_config.__dict__)

@app.route("/api/hp/start",     methods=["POST"])
@require_auth
def api_hp_start():
    if hp_bot and not hp_bot.running:
        hp_bot.start()
    return jsonify({"running": hp_bot.running if hp_bot else False})

@app.route("/api/hp/stop",      methods=["POST"])
@require_auth
def api_hp_stop():
    if hp_bot: hp_bot.stop()
    return jsonify({"running": False})

@app.route("/api/hp/emergency", methods=["POST"])
@require_auth
def api_hp_emergency():
    if hp_bot: hp_bot.emergency_stop()
    return jsonify({"emergency_stop": True})

@app.route("/api/hp/positions")
@require_auth
def api_hp_positions():
    if not hp_bot:
        return jsonify([])
    return jsonify([{
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
    } for pos in hp_bot.open_positions.values()])

@app.route("/api/hp/log")
@require_auth
def api_hp_log():
    if not hp_bot:
        return jsonify([])
    return jsonify([{
        "time":   r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "action": r.action,
        "market": r.market_question[:60],
        "side":   r.side,
        "price":  round(r.detected_price, 4),
        "size":   round(r.size_usdc, 2),
        "reason": r.reason,
    } for r in reversed(hp_bot.scan_log[-100:])])

# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Polymarket Trading Bots Dashboard")
    print("  Open: http://localhost:5000")
    if dash_config.PASSWORD_ENABLED:
        print("  🔒 Password protection: ENABLED")
    else:
        print("  ⚠️  Password protection: DISABLED")
        print("  To enable: set env var DASH_PASSWORD_ENABLED=true")
        print("             set env var DASH_PASSWORD=yourpassword")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
