"""
QuantBengal Engine — broker_api.py  v5.0
Angel One SmartAPI: Full integration layer
FIXES v5.0:
  - resolve_nfo_token() — looks up symboltoken before every NFO order (was blank, causing rejections)
  - get_positions() / get_pnl_summary() — null-safe, always return list/dict never None
  - square_off_all() — properly reads connected state, never crashes if not connected
  - Auto session renewal after 3 hours of inactivity
  - place_iron_condor() — resolves all 4 leg tokens before placing
"""

import os
import logging
import time
from datetime import datetime, timedelta
import pytz

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

# ── INDEX TOKEN MAP (NSE cash segment — for candle data & LTP) ─────────────────
SYMBOL_TOKENS = {
    "NIFTY":     "99926000",
    "BANKNIFTY": "99926009",
    "SENSEX":    "99919000",
}

ORDER_VARIETY  = "NORMAL"
ORDER_PRODUCT  = "INTRADAY"
ORDER_EXCHANGE = "NFO"


class IndianBrokerAPI:
    """Complete Angel One SmartAPI wrapper for QuantBengal — v5.0"""

    def __init__(self):
        self.api_key    = os.environ.get("BROKER_API_KEY", "")
        self.client_id  = os.environ.get("CLIENT_ID", "")
        self.password   = os.environ.get("PASSWORD", "")
        self.token      = os.environ.get("TOTP_TOKEN", "")
        self.obj        = None
        self.auth_token = None
        self.feed_token = None
        self.connected  = False
        self._session_ts = None
        self._connect()

    # ── SESSION ───────────────────────────────────────────────────────────────

    def _connect(self):
        if not all([self.api_key, self.client_id, self.password, self.token]):
            logger.error("Missing credentials. Set env vars: BROKER_API_KEY, CLIENT_ID, PASSWORD, TOTP_TOKEN")
            return
        try:
            from SmartApi.smartConnect import SmartConnect
            import pyotp
            self.obj  = SmartConnect(api_key=self.api_key)
            totp_code = pyotp.TOTP(self.token).now()
            data      = self.obj.generateSession(self.client_id, self.password, totp_code)
            if data and data.get("status"):
                self.auth_token  = data["data"]["jwtToken"]
                self.feed_token  = self.obj.getfeedToken()
                self.connected   = True
                self._session_ts = time.time()
                logger.info(f"Angel One session OK | Client: {self.client_id}")
            else:
                logger.error(f"Session failed: {data}")
        except Exception as e:
            logger.error(f"Connection error: {e}")

    def ensure_session(self):
        """Reconnect automatically if not connected or session older than 3 hours."""
        if not self.connected:
            self._connect()
            return
        if self._session_ts and (time.time() - self._session_ts) > 10800:
            logger.info("Session > 3h — auto-refreshing...")
            self._connect()

    # ── PROFILE ───────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        self.ensure_session()
        try:
            resp = self.obj.getProfile(self.feed_token)
            return resp.get("data", {}) if resp else {}
        except Exception as e:
            logger.error(f"get_profile: {e}")
            return {}

    # ── MARKET DATA ───────────────────────────────────────────────────────────

    def get_data(self, symbol: str = "BANKNIFTY",
                 interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """Fetch OHLCV candles. Always returns list, never raises."""
        self.ensure_session()
        if not self.connected:
            return []
        token = SYMBOL_TOKENS.get(symbol, SYMBOL_TOKENS["BANKNIFTY"])
        now   = datetime.now(IST)
        start = now - timedelta(days=days)
        params = {
            "exchange":    "NSE",
            "symboltoken": token,
            "interval":    interval,
            "fromdate":    start.strftime("%Y-%m-%d 09:15"),
            "todate":      now.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            resp = self.obj.getCandleData(params)
            if resp and resp.get("status"):
                candles = resp.get("data") or []
                logger.info(f"Candle data: {len(candles)} bars | {symbol}")
                return candles
            logger.error(f"Candle API error: {resp}")
        except Exception as e:
            logger.error(f"get_data: {e}")
        return []

    def get_ltp(self, exchange: str = "NSE",
                symbol: str = "BANKNIFTY", token: str = "99926009") -> float:
        """Get Last Traded Price. Returns 0.0 on failure."""
        self.ensure_session()
        if not self.connected:
            return 0.0
        try:
            resp = self.obj.ltpData(exchange, symbol, token)
            if resp and resp.get("status"):
                return float(resp["data"].get("ltp", 0))
        except Exception as e:
            logger.error(f"get_ltp: {e}")
        return 0.0

    # ── NFO TOKEN RESOLVER ────────────────────────────────────────────────────

    def resolve_nfo_token(self, trading_symbol: str) -> str:
        """
        Search Angel One for the symboltoken of a specific NFO option.
        e.g. "BANKNIFTY23DEC47000CE" -> "1234567"
        Returns "" if not found — order may still be attempted.
        """
        self.ensure_session()
        if not self.connected:
            return ""
        try:
            resp = self.obj.searchScrip(exchange="NFO", searchscrip=trading_symbol)
            if resp and resp.get("status") and resp.get("data"):
                items = resp["data"]
                if isinstance(items, list) and items:
                    # Prefer exact match
                    for item in items:
                        if item.get("tradingsymbol", "").upper() == trading_symbol.upper():
                            tok = str(item.get("symboltoken", ""))
                            logger.info(f"Token resolved: {trading_symbol} -> {tok}")
                            return tok
                    # Fallback to first result
                    return str(items[0].get("symboltoken", ""))
        except Exception as e:
            logger.error(f"resolve_nfo_token({trading_symbol}): {e}")
        return ""

    # ── ORDER MANAGEMENT ──────────────────────────────────────────────────────

    def place_order(self, signal: str, symbol: str = "BANKNIFTY",
                    quantity: int = 15, price: float = 0,
                    symbol_token: str = "") -> dict:
        """
        Place a live F&O market order.
        signal: "BUY_CALL" | "BUY_PUT" | "SELL_CALL" | "SELL_PUT"
        symbol: Full NFO trading symbol (e.g. BANKNIFTY23DEC47000CE)
        symbol_token: auto-resolved if not provided
        """
        self.ensure_session()
        if not self.connected:
            return {"status": False, "error": "Not connected to Angel One"}

        tx_map = {
            "BUY_CALL":  ("BUY",  "CE"),
            "BUY_PUT":   ("BUY",  "PE"),
            "SELL_CALL": ("SELL", "CE"),
            "SELL_PUT":  ("SELL", "PE"),
        }
        if signal not in tx_map:
            return {"status": False, "error": f"Unknown signal: {signal}"}

        transaction_type, _ = tx_map[signal]

        # Auto-resolve token if not supplied
        if not symbol_token:
            symbol_token = self.resolve_nfo_token(symbol)
            if not symbol_token:
                logger.warning(f"Token not resolved for {symbol} — order may be rejected by exchange")

        order_params = {
            "variety":         ORDER_VARIETY,
            "tradingsymbol":   symbol,
            "symboltoken":     symbol_token,
            "transactiontype": transaction_type,
            "exchange":        ORDER_EXCHANGE,
            "ordertype":       "MARKET",
            "producttype":     ORDER_PRODUCT,
            "duration":        "DAY",
            "price":           str(price),
            "squareoff":       "0",
            "stoploss":        "0",
            "quantity":        str(quantity),
        }

        logger.info(f"ORDER -> {signal} | {symbol} | Qty:{quantity} | Token:{symbol_token}")

        try:
            resp = self.obj.placeOrder(order_params)
            if resp and resp.get("status"):
                order_id = resp["data"].get("orderid", "")
                logger.info(f"ORDER PLACED | ID: {order_id}")
                return {"status": True, "order_id": order_id, "signal": signal}
            logger.error(f"Order rejected: {resp}")
            return {"status": False, "error": str(resp)}
        except Exception as e:
            logger.error(f"place_order exception: {e}")
            return {"status": False, "error": str(e)}

    def place_iron_condor(self, symbol: str, expiry: str,
                          short_call_strike: int, long_call_strike: int,
                          short_put_strike: int, long_put_strike: int,
                          quantity: int = 15) -> dict:
        """
        Place a complete Iron Condor (4-leg spread).
        Resolves symboltoken for each leg before placing.
        """
        legs = [
            (f"{symbol}{expiry}{short_call_strike}CE", "SELL_CALL"),
            (f"{symbol}{expiry}{long_call_strike}CE",  "BUY_CALL"),
            (f"{symbol}{expiry}{short_put_strike}PE",  "SELL_PUT"),
            (f"{symbol}{expiry}{long_put_strike}PE",   "BUY_PUT"),
        ]
        results = []
        for trading_symbol, leg_signal in legs:
            token  = self.resolve_nfo_token(trading_symbol)
            result = self.place_order(
                signal=leg_signal,
                symbol=trading_symbol,
                quantity=quantity,
                symbol_token=token
            )
            results.append({"leg": leg_signal, "symbol": trading_symbol, "result": result})
            time.sleep(0.4)   # rate-limit buffer between legs

        success = all(r["result"].get("status") for r in results)
        logger.info(f"Iron Condor {'ALL LEGS PLACED' if success else 'PARTIAL/FAILED'}")
        return {"status": success, "legs": results}

    def cancel_order(self, order_id: str, variety: str = ORDER_VARIETY) -> dict:
        self.ensure_session()
        try:
            return self.obj.cancelOrder(order_id, variety) or {}
        except Exception as e:
            logger.error(f"cancel_order: {e}")
            return {}

    def modify_order(self, order_id: str, new_price: float,
                     quantity: int, variety: str = ORDER_VARIETY) -> dict:
        self.ensure_session()
        try:
            params = {
                "variety": variety, "orderid": order_id,
                "ordertype": "LIMIT", "producttype": ORDER_PRODUCT,
                "duration": "DAY", "price": str(new_price), "quantity": str(quantity),
            }
            return self.obj.modifyOrder(params) or {}
        except Exception as e:
            logger.error(f"modify_order: {e}")
            return {}

    # ── POSITIONS & P&L ───────────────────────────────────────────────────────

    def get_positions(self) -> list:
        """Get open positions. Always returns list — never None."""
        self.ensure_session()
        if not self.connected:
            return []
        try:
            resp = self.obj.position()
            if resp and resp.get("status"):
                data = resp.get("data")
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"get_positions: {e}")
        return []

    def get_holdings(self) -> list:
        """Get equity holdings. Always returns list."""
        self.ensure_session()
        if not self.connected:
            return []
        try:
            resp = self.obj.holding()
            if resp and resp.get("status"):
                data = resp.get("data")
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"get_holdings: {e}")
        return []

    def get_order_book(self) -> list:
        """Today's orders. Always returns list."""
        self.ensure_session()
        if not self.connected:
            return []
        try:
            resp = self.obj.orderBook()
            if resp and resp.get("status"):
                data = resp.get("data")
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"get_order_book: {e}")
        return []

    def get_trade_book(self) -> list:
        """Today's executed trades. Always returns list."""
        self.ensure_session()
        if not self.connected:
            return []
        try:
            resp = self.obj.tradeBook()
            if resp and resp.get("status"):
                data = resp.get("data")
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"get_trade_book: {e}")
        return []

    def get_funds(self) -> dict:
        """Available margin and funds. Always returns dict."""
        self.ensure_session()
        if not self.connected:
            return {}
        try:
            resp = self.obj.rmsLimit()
            if resp and resp.get("status"):
                return resp.get("data") or {}
        except Exception as e:
            logger.error(f"get_funds: {e}")
        return {}

    def square_off_all(self) -> list:
        """
        Emergency: market-close all open positions.
        FIX v5.0: always null-safe — returns [] if not connected or no positions.
        """
        self.ensure_session()
        if not self.connected:
            logger.error("square_off_all: not connected")
            return []

        positions = self.get_positions()
        results   = []

        for pos in positions:
            try:
                net_qty = int(pos.get("netqty", 0))
            except (ValueError, TypeError):
                net_qty = 0
            if net_qty == 0:
                continue

            tx = "SELL" if net_qty > 0 else "BUY"
            order_params = {
                "variety":         ORDER_VARIETY,
                "tradingsymbol":   pos.get("tradingsymbol", ""),
                "symboltoken":     pos.get("symboltoken", ""),
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
                results.append({"symbol": pos.get("tradingsymbol", ""), "result": resp})
                logger.warning(f"SQUARE OFF: {pos.get('tradingsymbol','')} qty={abs(net_qty)}")
            except Exception as e:
                results.append({"symbol": pos.get("tradingsymbol", ""), "error": str(e)})
            time.sleep(0.25)

        logger.info(f"Square off complete — {len(results)} position(s) closed")
        return results

    def get_pnl_summary(self) -> dict:
        """
        Null-safe P&L summary.
        FIX v5.0: uses 'or 0' pattern on every field — never crashes on None values.
        Always returns a valid dict.
        """
        positions = self.get_positions()   # guaranteed to be a list
        try:
            realised   = sum(float(p.get("realisedprofitandloss")   or 0) for p in positions)
            unrealised = sum(float(p.get("unrealisedprofitandloss") or 0) for p in positions)
        except Exception:
            realised = unrealised = 0.0

        open_count = 0
        for p in positions:
            try:
                if int(p.get("netqty", 0)) != 0:
                    open_count += 1
            except Exception:
                pass

        return {
            "realised":   round(realised, 2),
            "unrealised": round(unrealised, 2),
            "total":      round(realised + unrealised, 2),
            "positions":  open_count,
        }
