"""
QuantBengal Engine — broker_api.py
Angel One SmartAPI: Full integration layer
Handles: session, market data, order management, positions, P&L, option chain
"""

import os
import logging
import json
import time
from SmartApi.smartConnect import SmartConnect
import pyotp
from datetime import datetime, timedelta
import pytz
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

# ─────────────────────────────────────────────
#  SYMBOL TOKEN MAP  (expand as needed)
# ─────────────────────────────────────────────
SYMBOL_TOKENS = {
    "NIFTY":    "99926000",
    "BANKNIFTY":"99926009",
    "SENSEX":   "99919000",
}

ORDER_VARIETY  = "NORMAL"
ORDER_PRODUCT  = "INTRADAY"  # or "CARRYFORWARD"
ORDER_EXCHANGE = "NFO"        # NSE F&O


class IndianBrokerAPI:
    """Complete Angel One SmartAPI wrapper for QuantBengal."""

    def __init__(self):
        self.api_key   = os.environ.get("BROKER_API_KEY", "")
        self.client_id = os.environ.get("CLIENT_ID", "")
        self.password  = os.environ.get("PASSWORD", "")
        self.token     = os.environ.get("TOTP_TOKEN", "")
        self.obj       = None
        self.auth_token = None
        self.feed_token = None
        self.connected  = False
        self._connect()

    # ─── SESSION ──────────────────────────────────────────────────────────────

    def _connect(self):
        if not all([self.api_key, self.client_id, self.password, self.token]):
            logger.error("Missing API credentials. Set env vars: BROKER_API_KEY, CLIENT_ID, PASSWORD, TOTP_TOKEN")
            return
        try:
            self.obj = SmartConnect(api_key=self.api_key)
            totp = pyotp.TOTP(self.token).now()
            data = self.obj.generateSession(self.client_id, self.password, totp)
            if data and data.get("status"):
                self.auth_token = data["data"]["jwtToken"]
                self.feed_token = self.obj.getfeedToken()
                self.connected  = True
                logger.info(f"✅ Angel One session active | Client: {self.client_id}")
            else:
                logger.error(f"Session failed: {data}")
        except Exception as e:
            logger.error(f"Connection error: {e}")

    def ensure_session(self):
        """Re-connect if session expired."""
        if not self.connected:
            self._connect()

    # ─── PROFILE ──────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        self.ensure_session()
        try:
            resp = self.obj.getProfile(self.feed_token)
            return resp.get("data", {}) if resp else {}
        except Exception as e:
            logger.error(f"get_profile error: {e}")
            return {}

    # ─── MARKET DATA ──────────────────────────────────────────────────────────

    def get_data(self, symbol: str = "BANKNIFTY", interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """Fetch OHLCV candles for given symbol & interval."""
        self.ensure_session()
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
                candles = resp.get("data", [])
                logger.info(f"Market data: {len(candles)} candles for {symbol}")
                return candles
            logger.error(f"Candle API error: {resp}")
        except Exception as e:
            logger.error(f"get_data error: {e}")
        return []

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        """Get Last Traded Price for a symbol."""
        self.ensure_session()
        try:
            resp = self.obj.ltpData(exchange, symbol, token)
            if resp and resp.get("status"):
                return float(resp["data"].get("ltp", 0))
        except Exception as e:
            logger.error(f"LTP error: {e}")
        return 0.0

    def get_option_chain(self, symbol: str, expiry_date: str, strike_price: float, option_type: str = "CE") -> dict:
        """Search for a specific option contract."""
        self.ensure_session()
        try:
            # Angel One searchScrip for NFO
            resp = self.obj.searchScrip(
                exchange="NFO",
                searchscrip=f"{symbol}{expiry_date}{int(strike_price)}{option_type}"
            )
            return resp.get("data", []) if resp else []
        except Exception as e:
            logger.error(f"Option chain error: {e}")
            return []

    # ─── ORDER MANAGEMENT ─────────────────────────────────────────────────────

    def place_order(self, signal: str, symbol: str = "BANKNIFTY",
                    quantity: int = 15, price: float = 0) -> dict:
        """
        Place a live F&O market order.
        signal: "BUY_CALL" | "BUY_PUT" | "SELL_CALL" | "SELL_PUT"
        """
        self.ensure_session()
        if not self.connected:
            logger.error("Cannot place order — not connected.")
            return {"status": False, "error": "Not connected"}

        # Parse signal into transactiontype + optiontype
        tx_map = {
            "BUY_CALL":  ("BUY",  "CE"),
            "BUY_PUT":   ("BUY",  "PE"),
            "SELL_CALL": ("SELL", "CE"),
            "SELL_PUT":  ("SELL", "PE"),
        }
        if signal not in tx_map:
            return {"status": False, "error": f"Unknown signal: {signal}"}

        transaction_type, option_type = tx_map[signal]

        # Build order params — uses MARKET order for guaranteed execution
        order_params = {
            "variety":          ORDER_VARIETY,
            "tradingsymbol":    symbol,       # Full NFO symbol e.g. BANKNIFTY23DEC47000CE
            "symboltoken":      "",           # Must be resolved before calling
            "transactiontype":  transaction_type,
            "exchange":         ORDER_EXCHANGE,
            "ordertype":        "MARKET",
            "producttype":      ORDER_PRODUCT,
            "duration":         "DAY",
            "price":            str(price),
            "squareoff":        "0",
            "stoploss":         "0",
            "quantity":         str(quantity),
        }

        logger.info(f"🚨 ORDER → {signal} | {symbol} | Qty:{quantity}")

        try:
            resp = self.obj.placeOrder(order_params)
            if resp and resp.get("status"):
                order_id = resp["data"].get("orderid", "")
                logger.info(f"✅ ORDER PLACED | ID: {order_id}")
                return {"status": True, "order_id": order_id, "signal": signal}
            else:
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
        Sell short call + Buy long call (wing) + Sell short put + Buy long put (wing)
        """
        legs = [
            ("SELL", f"{symbol}{expiry}{short_call_strike}CE", "SELL_CALL"),
            ("BUY",  f"{symbol}{expiry}{long_call_strike}CE",  "BUY_CALL"),
            ("SELL", f"{symbol}{expiry}{short_put_strike}PE",  "SELL_PUT"),
            ("BUY",  f"{symbol}{expiry}{long_put_strike}PE",   "BUY_PUT"),
        ]
        results = []
        for tx, trading_symbol, label in legs:
            result = self.place_order(signal=label, symbol=trading_symbol, quantity=quantity)
            results.append({"leg": label, "symbol": trading_symbol, "result": result})
            time.sleep(0.3)  # Avoid rate limiting between legs

        success = all(r["result"].get("status") for r in results)
        logger.info(f"Iron Condor {'✅ PLACED' if success else '❌ PARTIAL/FAILED'}")
        return {"status": success, "legs": results}

    def cancel_order(self, order_id: str, variety: str = ORDER_VARIETY) -> dict:
        self.ensure_session()
        try:
            resp = self.obj.cancelOrder(order_id, variety)
            return resp if resp else {}
        except Exception as e:
            logger.error(f"cancel_order error: {e}")
            return {}

    def modify_order(self, order_id: str, new_price: float, quantity: int,
                     variety: str = ORDER_VARIETY) -> dict:
        self.ensure_session()
        try:
            params = {
                "variety": variety,
                "orderid": order_id,
                "ordertype": "LIMIT",
                "producttype": ORDER_PRODUCT,
                "duration": "DAY",
                "price": str(new_price),
                "quantity": str(quantity),
            }
            resp = self.obj.modifyOrder(params)
            return resp if resp else {}
        except Exception as e:
            logger.error(f"modify_order error: {e}")
            return {}

    # ─── POSITIONS & P&L ──────────────────────────────────────────────────────

    def get_positions(self) -> list:
        """Get current open positions."""
        self.ensure_session()
        try:
            resp = self.obj.position()
            if resp and resp.get("status"):
                return resp.get("data", []) or []
        except Exception as e:
            logger.error(f"get_positions error: {e}")
        return []

    def get_holdings(self) -> list:
        """Get portfolio holdings."""
        self.ensure_session()
        try:
            resp = self.obj.holding()
            if resp and resp.get("status"):
                return resp.get("data", []) or []
        except Exception as e:
            logger.error(f"get_holdings error: {e}")
        return []

    def get_order_book(self) -> list:
        """Get today's order book."""
        self.ensure_session()
        try:
            resp = self.obj.orderBook()
            if resp and resp.get("status"):
                return resp.get("data", []) or []
        except Exception as e:
            logger.error(f"get_order_book error: {e}")
        return []

    def get_trade_book(self) -> list:
        """Get today's executed trades."""
        self.ensure_session()
        try:
            resp = self.obj.tradeBook()
            if resp and resp.get("status"):
                return resp.get("data", []) or []
        except Exception as e:
            logger.error(f"get_trade_book error: {e}")
        return []

    def get_funds(self) -> dict:
        """Get available margin and funds."""
        self.ensure_session()
        try:
            resp = self.obj.rmsLimit()
            if resp and resp.get("status"):
                return resp.get("data", {}) or {}
        except Exception as e:
            logger.error(f"get_funds error: {e}")
        return {}

    def square_off_all(self) -> list:
        """Emergency: square off all open positions."""
        self.ensure_session()
        positions = self.get_positions()
        results = []
        for pos in positions:
            net_qty = int(pos.get("netqty", 0))
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
                results.append({"symbol": pos["tradingsymbol"], "result": resp})
                logger.warning(f"🟥 SQUARE OFF: {pos['tradingsymbol']} qty={abs(net_qty)}")
            except Exception as e:
                results.append({"symbol": pos.get("tradingsymbol", ""), "error": str(e)})
            time.sleep(0.2)
        return results

    def get_pnl_summary(self) -> dict:
        """Calculate realised + unrealised P&L from positions."""
        positions = self.get_positions()
        realised   = sum(float(p.get("realisedprofitandloss", 0)) for p in positions)
        unrealised = sum(float(p.get("unrealisedprofitandloss", 0)) for p in positions)
        return {
            "realised":   round(realised, 2),
            "unrealised": round(unrealised, 2),
            "total":      round(realised + unrealised, 2),
            "positions":  len([p for p in positions if int(p.get("netqty", 0)) != 0]),
        }
