"""
Polymarket API Client Wrapper
Handles authentication, market data, and order management via py-clob-client.
"""
import logging
import time
import requests
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Safe import of py_clob_client ────────────────────────────────────────────
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds, OrderArgs,
        OrderType, PartialCreateOrderOptions,
        TradeParams, BookParams,
    )
    from py_clob_client.constants import POLYGON
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    logger.warning("py-clob-client not installed. Trading disabled. Run: pip install py-clob-client")


GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API  = "https://data-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"


class PolymarketClient:
    """
    Unified Polymarket API client supporting:
    - Market discovery via Gamma API
    - Real-time prices via CLOB API
    - Order placement via py-clob-client SDK
    - Trade history monitoring via Data API
    """

    def __init__(
        self,
        private_key: str = "",
        api_key: str = "",
        api_secret: str = "",
        api_passphrase: str = "",
        funder_address: str = "",
        chain_id: int = 137,
    ):
        self.private_key = private_key
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.funder_address = funder_address
        self.chain_id = chain_id
        self._client: Optional[Any] = None
        self.connected = False
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "PolymarketBot/1.0"})

    # ─── Connection ───────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Initialize the CLOB client with credentials."""
        if not CLOB_AVAILABLE:
            logger.warning("py-clob-client not available – read-only mode.")
            self.connected = False
            return False
        if not self.private_key:
            logger.warning("No private key provided – read-only mode.")
            self.connected = False
            return False
        try:
            creds = None
            if self.api_key and self.api_secret and self.api_passphrase:
                creds = ApiCreds(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    api_passphrase=self.api_passphrase,
                )
            self._client = ClobClient(
                host=CLOB_API,
                key=self.private_key,
                chain_id=self.chain_id,
                creds=creds,
                funder=self.funder_address or None,
            )
            # Derive API credentials if not provided
            if not creds:
                derived = self._client.derive_api_key()
                logger.info("Derived API credentials: %s", derived)
            self.connected = True
            logger.info("PolymarketClient connected successfully.")
            return True
        except Exception as e:
            logger.error("Failed to connect to Polymarket: %s", e)
            self.connected = False
            return False

    def disconnect(self):
        self._client = None
        self.connected = False

    # ─── Market Data (public – no auth needed) ────────────────────────────────

    def get_markets(self, limit: int = 100, offset: int = 0, active_only: bool = True) -> List[Dict]:
        """Fetch markets from Gamma API — multiple pages + crypto tag.

        Fetches up to 3 pages of 200 markets (600 total) PLUS a separate
        query for crypto-tagged markets (includes 5-min Bitcoin/ETH binary markets).
        All results are deduplicated by market 'id'.
        """
        seen_ids: set = set()
        all_markets: List[Dict] = []

        base_params: dict = {}
        if active_only:
            base_params["active"] = "true"
            base_params["closed"] = "false"

        # ── Fetch up to 3 pages of 200 markets each ────────────────────────────
        for page in range(3):
            try:
                params = {**base_params, "limit": 200, "offset": page * 200}
                resp = self._session.get(f"{GAMMA_API}/markets", params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                raw = data if isinstance(data, list) else data.get("markets", data.get("data", []))
                batch = [m for m in raw if isinstance(m, dict)]
                if not batch:
                    break   # no more results
                for m in batch:
                    mid = m.get("id") or m.get("conditionId") or m.get("question", "")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        all_markets.append(m)
            except Exception as e:
                logger.warning("get_markets page %d error: %s", page, e)
                break

        # ── Also fetch crypto-tagged markets (5M binary, BTC/ETH markets) ──────
        try:
            crypto_params = {**base_params, "limit": 200, "tag": "crypto"}
            resp = self._session.get(f"{GAMMA_API}/markets", params=crypto_params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw = data if isinstance(data, list) else data.get("markets", data.get("data", []))
                for m in raw:
                    if isinstance(m, dict):
                        mid = m.get("id") or m.get("conditionId") or m.get("question", "")
                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            all_markets.append(m)
        except Exception as e:
            logger.warning("get_markets crypto tag error: %s", e)

        logger.debug("get_markets: fetched %d unique markets total", len(all_markets))
        return all_markets


    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Fetch a single market by its slug."""
        try:
            resp = self._session.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [])
            return markets[0] if markets else None
        except Exception as e:
            logger.error("get_market_by_slug error: %s", e)
            return None

    def get_order_book(self, token_id: str) -> Optional[Dict]:
        """Fetch order book for a token (YES/NO side)."""
        try:
            resp = self._session.get(f"{CLOB_API}/book", params={"token_id": token_id}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("get_order_book error: %s", e)
            return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get the current mid-price for a token."""
        try:
            resp = self._session.get(f"{CLOB_API}/midpoint", params={"token_id": token_id}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            mid = data.get("mid") or data.get("price")
            return float(mid) if mid is not None else None
        except Exception as e:
            logger.error("get_midpoint error: %s", e)
            return None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get best bid/ask price."""
        try:
            resp = self._session.get(
                f"{CLOB_API}/price",
                params={"token_id": token_id, "side": side},
                timeout=10
            )
            resp.raise_for_status()
            return float(resp.json().get("price", 0))
        except Exception as e:
            logger.error("get_price error: %s", e)
            return None

    def get_all_markets_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """Batch fetch midpoints for multiple tokens."""
        prices = {}
        for tid in token_ids:
            p = self.get_midpoint(tid)
            if p is not None:
                prices[tid] = p
        return prices

    # ─── User / Trader Data ───────────────────────────────────────────────────

    def get_trader_positions(self, address: str) -> List[Dict]:
        """Fetch open positions for a given wallet address."""
        try:
            resp = self._session.get(
                f"{DATA_API}/positions",
                params={"user": address.lower()},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("positions", [])
        except Exception as e:
            logger.error("get_trader_positions error: %s", e)
            return []

    def get_trader_trades(self, address: str, limit: int = 50) -> List[Dict]:
        """Fetch recent trades for a given wallet address."""
        try:
            resp = self._session.get(
                f"{DATA_API}/activity",
                params={"user": address.lower(), "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("activity", [])
        except Exception as e:
            logger.error("get_trader_trades error: %s", e)
            return []

    def get_my_positions(self) -> List[Dict]:
        """Fetch authenticated user positions."""
        if not self.funder_address:
            return []
        return self.get_trader_positions(self.funder_address)

    def get_my_balance(self) -> float:
        """Fetch USDC balance from the CLOB API (with Data API fallback)."""
        # Try CLOB SDK first
        if self.connected and self._client:
            try:
                bal = self._client.get_balance_allowance()
                # Response can be: {"balance": "123.45"} or {"USDC": {"balance": ...}}
                # or even a BalanceAllowanceResponse object
                if hasattr(bal, "balance"):
                    return float(bal.balance or 0)
                if isinstance(bal, dict):
                    # Try common keys
                    for key in ("balance", "USDC", "usdc", "amount"):
                        v = bal.get(key, None)
                        if v is not None:
                            if isinstance(v, dict):
                                return float(v.get("balance", 0) or 0)
                            return float(v or 0)
            except Exception as e:
                logger.warning("CLOB balance error: %s — trying Data API", e)

        # Fallback: query Polygon USDC balance via Data API
        if self.funder_address:
            try:
                url = f"{DATA_API}/value?user={self.funder_address}"
                r = self._session.get(url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    # data = {"value": 123.45} or similar
                    val = data.get("value") or data.get("portfolio_value") or data.get("balance", 0)
                    return float(val or 0)
            except Exception as e:
                logger.warning("Data API balance error: %s", e)
        return 0.0

    # ─── Order Management ────────────────────────────────────────────────────

    def place_market_order(self, token_id: str, side: str, amount_usdc: float) -> Optional[Dict]:
        """Place a market order using FOK (Fill-Or-Kill) — works on ALL py-clob-client versions.

        On Polymarket's CLOB, a 'market order' = a limit order with OrderType.FOK
        at an aggressive price (0.99 for BUY, 0.01 for SELL).
        FOK fills immediately at the best available price or cancels entirely.
        Raises on failure so caller sees the real error message.
        """
        if not (self.connected and self._client):
            raise RuntimeError("Not connected — save credentials and click Connect & Save first")

        side_upper = side.upper()
        # Aggressive limit price = willing to pay up to $0.99 for BUY (acts like market buy)
        fok_price = 0.999 if side_upper == "BUY" else 0.001
        shares = round(amount_usdc / fok_price, 4)

        order_args = OrderArgs(
            token_id=token_id,
            price=fok_price,
            size=shares,
            side=side_upper,
        )
        signed = self._client.create_order(order_args)
        result = self._client.post_order(signed, OrderType.FOK)  # FOK = instant fill at market price
        logger.info("Market (FOK) order placed: %s", result)
        return result

    def place_limit_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> Optional[Dict]:
        """Place a GTC limit (maker) order. Raises on failure so caller sees real error."""
        if not (self.connected and self._client):
            raise RuntimeError("Not connected — save credentials and click Connect & Save first")
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
        )
        signed = self._client.create_order(order_args)
        resp = self._client.post_order(signed, OrderType.GTC)
        logger.info("Limit order placed: %s", resp)
        return resp

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not (self.connected and self._client):
            return False
        try:
            self._client.cancel(order_id=order_id)
            return True
        except Exception as e:
            logger.error("cancel_order error: %s", e)
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if not (self.connected and self._client):
            return False
        try:
            self._client.cancel_all()
            return True
        except Exception as e:
            logger.error("cancel_all_orders error: %s", e)
            return False


# ─── Heartbeat / ping helper ──────────────────────────────────────────────────

def ping_polymarket() -> bool:
    """Quick reachability check."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={"limit": 1}, timeout=5)
        return r.status_code == 200
    except Exception:
        return False
