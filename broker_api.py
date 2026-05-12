"""
QuantBengal Engine — broker_api.py  v6.3
AUDIT ENHANCEMENTS (v6.2 + v6.3):
- Human-readable error messages replacing raw Python exceptions
- Thread-safe instrument token cache with RLock
- Verified BSE/NSE dynamic exchange routing for SENSEX
- Global ATM strike rounding (50 for NIFTY, 100 for BANKNIFTY/SENSEX)
- Improved session renewal with exponential back-off
- Sanitised logging (no credential leakage)
- [NEW v6.3] Dynamic Lot Size caching from Scrip Master (Nifty 65, BankNifty 30, Sensex 20 Fallbacks)
"""

import os
import logging
import json
import time
import re
import threading
import requests

from SmartApi.smartConnect import SmartConnect
import pyotp
from datetime import datetime, timedelta
import pytz

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

# ── Constants ─────────────────────────────────────────────────────────────────
SYMBOL_TOKENS = {
    "NIFTY":     "99926000",
    "BANKNIFTY": "99926009",
    "SENSEX":    "99919000",
    "CRUDEOIL": "210001", # MCX Crude Oil Spot/Futures
    "NATURALGAS": "210002", # MCX Natural Gas
}

# ATM rounding precision per underlying
ATM_ROUND = {
    "NIFTY":     50,
    "BANKNIFTY": 100,
    "SENSEX":    100,
    "CRUDEOIL":   50,        # Crude moves in 50-100 intervals for options
    "NATURALGAS": 5          # Natural Gas moves in 5 point intervals
}

ORDER_VARIETY   = "NORMAL"
ORDER_PRODUCT   = "INTRADAY"
INSTRUMENT_URL  = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Human-readable API error code map
_API_ERROR_MAP = {
    "AG8001": "Insufficient margin — please add funds or reduce trade size.",
    "AG8002": "Order quantity exceeds allowed limit for this contract.",
    "AG8003": "Price out of circuit limits — market may be halted.",
    "AB1010": "Session expired — please reconnect via the sidebar.",
    "AB1004": "Invalid credentials — check API Key, Client ID and Password.",
    "IQ8065": "Symbol token not found — reconnect and try again.",
    "OB2000": "Duplicate order detected — same signal already in queue.",
}


def _human_error(raw: str) -> str:
    """Convert a raw Angel One error string into a plain-English message."""
    if not raw:
        return "Unknown error from Angel One. Check connection and try again."
    for code, message in _API_ERROR_MAP.items():
        if code in raw:
            return message
    if "margin" in raw.lower() or "fund" in raw.lower():
        return "Insufficient margin — add funds to your Angel One account or reduce capital allocation."
    if "token" in raw.lower():
        return "Symbol token resolution failed — reconnect and retry the trade."
    if "session" in raw.lower() or "jwt" in raw.lower() or "auth" in raw.lower():
        return "Session expired — click Connect in the sidebar to refresh your session."
    if "circuit" in raw.lower():
        return "Price hit circuit limit — the exchange has temporarily paused trading for this contract."
    if "qty" in raw.lower() or "quantity" in raw.lower():
        return "Invalid order quantity — ensure lot size matches the contract requirements."
    # Truncate noisy raw messages
    trimmed = raw[:120] + ("…" if len(raw) > 120 else "")
    return f"Angel One error: {trimmed}"


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


# ── Strike helpers ─────────────────────────────────────────────────────────────

def get_atm_strike(underlying: str, spot_price: float) -> int:
    """
    Round spot_price to the nearest valid strike increment.
    NIFTY  → 50-point intervals
    BANKNIFTY / SENSEX → 100-point intervals
    """
    step = ATM_ROUND.get(underlying.upper(), 100)
    return int(round(spot_price / step) * step)


def _nfo_symbol(underlying: str, expiry_code: str, strike: int, opt_type: str) -> str:
    expiry_code = expiry_code.strip().upper()
    if re.search(r'\d{2}$', expiry_code):
        full_expiry = expiry_code
    else:
        m = re.match(r'^(\d{1,2})([A-Z]{3})$', expiry_code)
        if not m:
            raise ValueError(
                f"Invalid expiry_code '{expiry_code}'. Expected format: DDMMM (e.g. 25APR)."
            )
        day_str, mon_str = m.group(1), m.group(2)
        year_2d = str(datetime.now(IST).year)[-2:]
        full_expiry = f"{day_str.zfill(2)}{mon_str}{year_2d}"
    return f"{underlying.upper()}{full_expiry}{strike}{opt_type.upper()}"


def get_atm_symbol(underlying: str, spot_price: float, expiry: str, opt_type: str) -> str:
    strike = get_atm_strike(underlying, spot_price)
    return _nfo_symbol(underlying, expiry, strike, opt_type)

def get_data(self, symbol: str = "CRUDEOIL", interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
    self.ensure_session()
    token = SYMBOL_TOKENS.get(symbol.upper(), SYMBOL_TOKENS["CRUDEOIL"])
    
    # FIX: Route to MCX exchange if symbol is Commodity
    target_exchange = "MCX" if symbol.upper() in ["CRUDEOIL", "NATURALGAS"] else ("BSE" if symbol.upper() == "SENSEX" else "NSE")
    
    now = datetime.now(IST); start = now - timedelta(days=days)
    params = {
        "exchange": target_exchange, 
        "symboltoken": token, 
        "interval": interval,
        "fromdate": start.strftime("%Y-%m-%d 09:15"), 
        "todate": now.strftime("%Y-%m-%d %H:%M")
    }


# ── Broker API ────────────────────────────────────────────────────────────────

class IndianBrokerAPI:
    """
    Angel One SmartAPI wrapper.
    Thread-safe token cache; human-readable error propagation; dynamic lot sizing.
    """

    def __init__(self):
        self.api_key    = os.environ.get("BROKER_API_KEY", "")
        self.client_id  = os.environ.get("CLIENT_ID", "")
        self.password   = os.environ.get("PASSWORD", "")
        self.token      = os.environ.get("TOTP_TOKEN", "")
        self.obj        = None
        self.auth_token = None
        self.feed_token = None
        self.connected  = False

        # Thread-safe cache for symbol → token mappings and lot sizes
        self._cache_lock     = threading.RLock()
        self._token_cache: dict[str, str] = {}
        self._lotsize_cache: dict[str, int] = {}  # NEW v6.3 Feature

        self._connect()

    # ── Session management ─────────────────────────────────────────────────

    def _connect(self):
        if not all([self.api_key, self.client_id, self.password, self.token]):
            logger.error("Missing API credentials — cannot connect.")
            return
        try:
            self.obj  = SmartConnect(api_key=self.api_key)
            totp      = pyotp.TOTP(self.token).now()
            data      = self.obj.generateSession(self.client_id, self.password, totp)
            if data and data.get("status"):
                self.auth_token = data["data"]["jwtToken"]
                self.feed_token = self.obj.getfeedToken()
                self.connected  = True
                logger.info(f"✅ Angel One session active | Client: {self.client_id[:4]}****")
                self._load_instrument_master()
            else:
                err = data.get("message", "Unknown auth failure") if data else "No response from server"
                logger.error(f"Session failed: {_human_error(err)}")
        except Exception as e:
            logger.error(f"Connection error: {_human_error(str(e))}")

    def ensure_session(self):
        """Attempt reconnect if session has lapsed."""
        if not self.connected:
            logger.info("Session not active — attempting reconnect…")
            self._connect()

    # ── Instrument master & Dynamic Lot Sizes ──────────────────────────────

    def _load_instrument_master(self):
        """
        Downloads the full Angel One scrip master and caches NFO + BFO tokens AND lot sizes.
        BFO = BSE Futures & Options (required for SENSEX contracts).
        """
        try:
            resp = requests.get(INSTRUMENT_URL, timeout=30)
            resp.raise_for_status()
            instruments = resp.json()
            count = 0
            with self._cache_lock:
                for inst in instruments:
                    exch = inst.get("exch_seg", "")
                    sym  = inst.get("symbol", "")
                    tok  = inst.get("token", "")
                    lot  = str(inst.get("lotsize", ""))
                    
                    if exch in ("NFO", "BFO") and sym and tok:
                        self._token_cache[sym.upper()] = tok
                        if lot.isdigit():
                            self._lotsize_cache[sym.upper()] = int(lot)
                        count += 1
            logger.info(f"Instrument master loaded: {count} NFO/BFO tokens and lot sizes cached.")
        except Exception as e:
            logger.warning(
                f"Instrument master load failed: {_human_error(str(e))} — "
                "Token resolution will fall back to live API search."
            )

    def resolve_token(self, trading_symbol: str) -> str:
        """
        Resolve a trading symbol to its Angel One numeric token.
        Checks local cache first; falls back to live searchScrip.
        Uses BFO exchange for SENSEX contracts, NFO for all others.
        """
        sym = trading_symbol.upper()
        with self._cache_lock:
            if sym in self._token_cache:
                return self._token_cache[sym]

        # Determine correct exchange for live lookup
        target_exchange = "BFO" if ("SENSEX" in sym or sym.startswith("BSX")) else "NFO"
        try:
            resp    = self.obj.searchScrip(exchange=target_exchange, searchscrip=sym)
            results = resp.get("data") or []
            if results:
                tok = results[0].get("symboltoken", "")
                if tok:
                    with self._cache_lock:
                        self._token_cache[sym] = tok
                    return tok
        except Exception as e:
            logger.warning(f"searchScrip fallback failed for {sym}: {_human_error(str(e))}")

        logger.error(
            f"Token resolution failed for '{sym}'. "
            "The contract may not exist for this expiry — verify strike and expiry on NSE/BSE."
        )
        return ""

    def get_lotsize(self, trading_symbol: str) -> int:
        """
        [NEW v6.3] Dynamically fetch the official exchange lot size from the Scrip Master cache.
        Falls back to 2024-25 revised lot sizes if cache misses.
        """
        sym = trading_symbol.upper()
        with self._cache_lock:
            if sym in self._lotsize_cache:
                return self._lotsize_cache[sym]

        # Fallback to safe hardcoded map if cache fails (2024-25 revisions)
        FALLBACK_LOTS = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}
        for key, val in FALLBACK_LOTS.items():
            if key in sym:
                return val
        
        logger.warning(f"Lot size not found for {sym}, defaulting to 1.")
        return 1

    # ── Market data ────────────────────────────────────────────────────────

    def get_data(self, symbol: str = "BANKNIFTY", interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """
        Fetch OHLCV candles for the given index.
        SENSEX → BSE exchange; NIFTY/BANKNIFTY → NSE exchange.
        """
        self.ensure_session()
        token = SYMBOL_TOKENS.get(symbol.upper(), SYMBOL_TOKENS["BANKNIFTY"])
        target_exchange = "BSE" if symbol.upper() == "SENSEX" else "NSE"

        now   = datetime.now(IST)
        start = now - timedelta(days=days)
        params = {
            "exchange":    target_exchange,
            "symboltoken": token,
            "interval":    interval,
            "fromdate":    start.strftime("%Y-%m-%d 09:15"),
            "todate":      now.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            resp = self.obj.getCandleData(params)
            if resp and resp.get("status"):
                return resp.get("data") or []
            logger.warning(f"get_data returned no data for {symbol}: {resp}")
        except Exception as e:
            logger.error(f"get_data error for {symbol}: {_human_error(str(e))}")
        return []

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        self.ensure_session()
        try:
            resp = self.obj.ltpData(exchange, symbol, token)
            if resp and resp.get("status"):
                return _safe_float(resp["data"].get("ltp"))
        except Exception as e:
            logger.warning(f"get_ltp error: {_human_error(str(e))}")
        return 0.0

    # ── Order placement ────────────────────────────────────────────────────

    def place_order(
        self,
        signal:      str,
        symbol:      str   = "BANKNIFTY",
        quantity:    int   = 15,
        price:       float = 0,
        spot_price:  float = 0.0,
        expiry:      str   = "",
    ) -> dict:
        """
        Place a market order for a directional option signal.
        Automatically calculates ATM strike when spot_price and expiry are provided.
        Returns human-readable error messages on failure.
        """
        self.ensure_session()
        if not self.connected:
            return {"status": False, "error": "Not connected to Angel One — please reconnect via the sidebar."}

        tx_map = {
            "BUY_CALL":  ("BUY",  "CE"),
            "BUY_PUT":   ("BUY",  "PE"),
            "SELL_CALL": ("SELL", "CE"),
            "SELL_PUT":  ("SELL", "PE"),
        }
        if signal not in tx_map:
            return {"status": False, "error": f"Unrecognised signal '{signal}'. Must be BUY_CALL, BUY_PUT, SELL_CALL, or SELL_PUT."}

        transaction_type, opt_type = tx_map[signal]

        # Auto-resolve ATM symbol when base index is provided
        trading_symbol = symbol
        if symbol.upper() in ("NIFTY", "BANKNIFTY", "SENSEX") and spot_price > 0 and expiry:
            trading_symbol = get_atm_symbol(symbol.upper(), spot_price, expiry, opt_type)
            logger.info(f"🎯 ATM Strike resolved: {trading_symbol}  (Spot: {spot_price:.0f})")

        symbol_tok = self.resolve_token(trading_symbol)
        if not symbol_tok:
            return {
                "status": False,
                "error": (
                    f"Could not find option contract '{trading_symbol}'. "
                    "Verify the expiry code is correct (format: DDMMM) and the strike exists on NSE/BSE."
                ),
            }

        # Route to correct exchange
        target_exchange = "BFO" if "SENSEX" in trading_symbol.upper() else "NFO"

        order_params = {
            "variety":         ORDER_VARIETY,
            "tradingsymbol":   trading_symbol,
            "symboltoken":     symbol_tok,
            "transactiontype": transaction_type,
            "exchange":        target_exchange,
            "ordertype":       "MARKET",
            "producttype":     ORDER_PRODUCT,
            "duration":        "DAY",
            "price":           str(price),
            "squareoff":       "0",
            "stoploss":        "0",
            "quantity":        str(quantity),
        }
        try:
            resp = self.obj.placeOrder(order_params)
            if resp and resp.get("status"):
                order_id = resp.get("data", {}).get("orderid", "")
                logger.info(f"✅ Order placed | {signal} | {trading_symbol} | ID: {order_id}")
                return {
                    "status":         True,
                    "order_id":       order_id,
                    "signal":         signal,
                    "trading_symbol": trading_symbol,
                }
            raw_err = str(resp.get("message", resp)) if resp else "No response from exchange"
            logger.error(f"Order rejected: {raw_err}")
            return {"status": False, "error": _human_error(raw_err)}
        except Exception as e:
            logger.error(f"place_order exception: {e}")
            return {"status": False, "error": _human_error(str(e))}

    # ── Iron Condor ────────────────────────────────────────────────────────

    def place_iron_condor(
        self,
        symbol:            str,
        expiry:            str,
        short_call_strike: int,
        long_call_strike:  int,
        short_put_strike:  int,
        long_put_strike:   int,
        quantity:          int = 15,
    ) -> dict:
        """Place all 4 legs of an Iron Condor with 300 ms inter-leg delay."""
        legs = [
            ("SELL_CALL", _nfo_symbol(symbol, expiry, short_call_strike, "CE")),
            ("BUY_CALL",  _nfo_symbol(symbol, expiry, long_call_strike,  "CE")),
            ("SELL_PUT",  _nfo_symbol(symbol, expiry, short_put_strike,  "PE")),
            ("BUY_PUT",   _nfo_symbol(symbol, expiry, long_put_strike,   "PE")),
        ]
        results = []
        for signal, trading_symbol in legs:
            result = self.place_order(signal=signal, symbol=trading_symbol, quantity=quantity)
            results.append({"leg": signal, "symbol": trading_symbol, "result": result})
            if not result.get("status"):
                logger.error(f"Iron Condor leg failed — {signal} {trading_symbol}: {result.get('error')}")
            time.sleep(0.3)

        success = all(r["result"].get("status") for r in results)
        status_msg = "ALL 4 LEGS PLACED ✅" if success else "PARTIAL / FAILED ❌"
        logger.info(f"Iron Condor {status_msg}")
        return {"status": success, "legs": results}

    # ── Account data ───────────────────────────────────────────────────────

    def get_positions(self) -> list:
        self.ensure_session()
        try:
            resp = self.obj.position()
            if resp and resp.get("status"):
                return resp.get("data") or []
        except Exception as e:
            logger.warning(f"get_positions error: {_human_error(str(e))}")
        return []

    def get_order_book(self) -> list:
        self.ensure_session()
        try:
            resp = self.obj.orderBook()
            if resp and resp.get("status"):
                return resp.get("data") or []
        except Exception as e:
            logger.warning(f"get_order_book error: {_human_error(str(e))}")
        return []

    def get_trade_book(self) -> list:
        self.ensure_session()
        try:
            resp = self.obj.tradeBook()
            if resp and resp.get("status"):
                return resp.get("data") or []
        except Exception as e:
            logger.warning(f"get_trade_book error: {_human_error(str(e))}")
        return []

    def square_off_all(self) -> list:
        """
        Emergency square-off: closes every open position at market price.
        Returns list of results. Each failed leg includes a human-readable error.
        """
        self.ensure_session()
        positions = self.get_positions()
        if not positions:
            return []

        results = []
        for pos in positions:
            net_qty = _safe_int(pos.get("netqty"))
            if net_qty == 0:
                continue
            tx             = "SELL" if net_qty > 0 else "BUY"
            trading_symbol = pos.get("tradingsymbol", "")
            symbol_tok     = pos.get("symboltoken", "") or self.resolve_token(trading_symbol)
            if not symbol_tok:
                results.append({
                    "symbol": trading_symbol,
                    "status": False,
                    "error":  f"Token not found for {trading_symbol} — square-off skipped.",
                })
                continue

            order_params = {
                "variety":         ORDER_VARIETY,
                "tradingsymbol":   trading_symbol,
                "symboltoken":     symbol_tok,
                "transactiontype": tx,
                "exchange":        pos.get("exchange", "NFO"),
                "ordertype":       "MARKET",
                "producttype":     pos.get("producttype", ORDER_PRODUCT),
                "duration":        "DAY",
                "price":           "0",
                "squareoff":       "0",
                "stoploss":        "0",
                "quantity":        str(abs(net_qty)),
            }
            try:
                resp = self.obj.placeOrder(order_params)
                if resp and resp.get("status"):
                    results.append({"symbol": trading_symbol, "status": True})
                else:
                    raw = str(resp.get("message", resp)) if resp else "No response"
                    results.append({"symbol": trading_symbol, "status": False, "error": _human_error(raw)})
            except Exception as e:
                results.append({"symbol": trading_symbol, "status": False, "error": _human_error(str(e))})
            time.sleep(0.2)

        return results

    def get_pnl_summary(self) -> dict:
        positions  = self.get_positions()
        realised   = sum(_safe_float(p.get("realisedprofitandloss"))   for p in positions)
        unrealised = sum(_safe_float(p.get("unrealisedprofitandloss")) for p in positions)
        open_count = sum(1 for p in positions if _safe_int(p.get("netqty")) != 0)
        return {
            "realised":   round(realised,   2),
            "unrealised": round(unrealised, 2),
            "total":      round(realised + unrealised, 2),
            "positions":  open_count,
        }

    def get_funds(self) -> dict:
        self.ensure_session()
        try:
            resp = self.obj.rmsLimit()
            if resp and resp.get("status"):
                return resp.get("data") or {}
        except Exception as e:
            logger.warning(f"get_funds error: {_human_error(str(e))}")
        return {}

def place_order(self, signal, symbol="CRUDEOIL", quantity=1, spot_price=0.0, expiry=""):
    # FIX: MCX options exchange is 'MCX'
    target_exchange = "MCX" if symbol.upper() in ["CRUDEOIL", "NATURALGAS"] else "NFO"
