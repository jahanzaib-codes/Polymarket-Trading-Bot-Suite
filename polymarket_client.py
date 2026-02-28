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
        ApiCreds, OrderArgs, MarketOrderArgs,
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
        """Fetch markets from the Gamma API.

        The Gamma API returns a flat list of market dicts with these key fields:
          - id, question
          - clobTokenIds  : ["<yes_token_id>", "<no_token_id>"]
          - outcomes      : ["Yes", "No"]   (strings)
          - outcomePrices : ["0.97", "0.03"] (strings)
          - volumeNum, liquidityNum
          - active, closed
        """
        try:
            params = {"limit": limit, "offset": offset}
            if active_only:
                params["active"] = "true"
                params["closed"] = "false"
            resp = self._session.get(f"{GAMMA_API}/markets", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            raw = data if isinstance(data, list) else data.get("markets", data.get("data", []))
            # Only keep proper dict items — filter out any stray strings/nulls
            return [m for m in raw if isinstance(m, dict)]
        except Exception as e:
            logger.error("get_markets error: %s", e)
            return []

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
        """Fetch USDC balance from the CLOB API."""
        if not (self.connected and self._client):
            return 0.0
        try:
            bal = self._client.get_balance_allowance()
            return float(bal.get("balance", 0))
        except Exception as e:
            logger.error("get_my_balance error: %s", e)
            return 0.0

    # ─── Order Management ────────────────────────────────────────────────────

    def place_market_order(self, token_id: str, side: str, amount_usdc: float) -> Optional[Dict]:
        """Place a market (taker) order."""
        if not (self.connected and self._client):
            logger.warning("Not connected – cannot place order.")
            return None
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usdc,
            )
            order = self._client.create_and_post_market_order(order_args)
            logger.info("Market order placed: %s", order)
            return order
        except Exception as e:
            logger.error("place_market_order error: %s", e)
            return None

    def place_limit_order(
        self, token_id: str, side: str, price: float, size: float
    ) -> Optional[Dict]:
        """Place a GTC limit (maker) order."""
        if not (self.connected and self._client):
            logger.warning("Not connected – cannot place order.")
            return None
        try:
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
        except Exception as e:
            logger.error("place_limit_order error: %s", e)
            return None

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
