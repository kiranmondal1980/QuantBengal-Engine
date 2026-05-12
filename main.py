"""
QuantBengal Engine — main.py  v6.0
GitHub Actions scheduler entry point.
- AUTOMATION FIX: Synchronised with v6.3 Backend (Multi-Index & ATM Strike)
- SAFETY FIX: Hardcoded Safe Trading Hours (10:30 - 14:30 IST)
- FEATURE PRESERVATION: All JSON logging, Risk Checks, and Position Summaries intact.
"""

import logging
import json
import os
import sys
from datetime import datetime
import pytz

from broker_api import IndianBrokerAPI
from strategy import (MomentumStrategy, IronCondorStrategy,
                      MorningBreakoutStrategy, RiskManager)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

# ── CONFIG — all injected from GitHub Actions Variables/Secrets ──────────────
DRY_RUN         = os.environ.get("DRY_RUN", "true").lower() == "true"
CAPITAL         = float(os.environ.get("CAPITAL", "20000"))
VIX_VALUE       = float(os.environ.get("VIX", "15.0"))

# NEW: Multi-Index & Strategy Configuration
# These must be set in GitHub Settings -> Secrets and Variables -> Actions -> Variables
ACTIVE_CATEGORY = os.environ.get("STRATEGY", "MOMENTUM").upper() # MOMENTUM | IRON_CONDOR | BREAKOUT
STRATEGY_NAME   = os.environ.get("STRATEGY_NAME", "SuperTrend + RSI")
INDEX_CHOICE    = os.environ.get("INDEX_CHOICE", "NIFTY").upper()
EXPIRY_DATE     = os.environ.get("EXPIRY_DATE", "25APR")

# Safe Hours Configuration (10:30 AM to 02:30 PM)
SAFE_START_HOUR = 10
SAFE_START_MIN  = 30
SAFE_END_HOUR   = 14
SAFE_END_MIN    = 30

# Iron Condor specific
IC_EXPIRY       = os.environ.get("IC_EXPIRY", "23DEC")
IC_SPOT         = float(os.environ.get("BANKNIFTY_SPOT", "0"))


def is_market_hours() -> bool:
    """True only during the User-Defined Safe Window: 10:30–14:30 IST."""
    now = datetime.now(IST)
    if now.weekday() > 4:
        return False
    
    # Strictly follow the 10:30 - 14:30 window for automation safety
    start = now.replace(hour=SAFE_START_HOUR, minute=SAFE_START_MIN, second=0, microsecond=0)
    end   = now.replace(hour=SAFE_END_HOUR,   minute=SAFE_END_MIN,   second=0, microsecond=0)
    
    return start <= now <= end


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _clean_result(result: dict) -> dict:
    """Remove non-serialisable keys (e.g. DataFrame) before JSON logging."""
    return {
        k: v for k, v in result.items()
        if k != "df" and not hasattr(v, 'to_dict') and not hasattr(v, 'to_json')
    }


def run_bot():
    logger.info("=" * 60)
    logger.info(f"  QuantBengal Cloud Engine START")
    logger.info(f"  INDEX: {INDEX_CHOICE} | STRATEGY: {STRATEGY_NAME}")
    logger.info(f"  DRY_RUN={DRY_RUN} | Capital=₹{CAPITAL:,.0f} | Expiry={EXPIRY_DATE}")
    logger.info("=" * 60)

    # ── SAFE HOURS GATE ──────────────────────────────────────────────────────
    if not is_market_hours():
        logger.info(f"⏳ Current Time {datetime.now(IST).strftime('%H:%M')} is outside Safe Hours ({SAFE_START_HOUR}:{SAFE_START_MIN} - {SAFE_END_HOUR}:{SAFE_END_MIN}). Engine Sleep.")
        sys.exit(0)

    # ── BROKER CONNECT ───────────────────────────────────────────────────────
    broker = IndianBrokerAPI()
    if not broker.connected:
        logger.error("❌ Broker connection failed — aborting this run.")
        sys.exit(1)

    # ── RISK CHECK ───────────────────────────────────────────────────────────
    risk = RiskManager(capital=CAPITAL)
    pnl  = broker.get_pnl_summary()
    logger.info(
        f"📊 P&L | Realised: ₹{pnl['realised']:,.0f}"
        f" | Unrealised: ₹{pnl['unrealised']:,.0f}"
        f" | Total: ₹{pnl['total']:,.0f}"
    )

    if not risk.check_daily_loss(pnl['total']):
        logger.error("🛑 Daily loss limit reached — halting for today.")
        sys.exit(0)

    # ── RUN SELECTED STRATEGY ────────────────────────────────────────────────
    result = {}

    if ACTIVE_CATEGORY == "MOMENTUM":
        # Pass the specific algorithm name (e.g., 'SuperTrend + RSI') to the strategy engine
        strategy = MomentumStrategy(broker, risk, strategy_name=STRATEGY_NAME)
        # check_and_trade now uses the dynamic Index Choice and Expiry
        result = strategy.check_and_trade(
            dry_run=DRY_RUN, 
            symbol=INDEX_CHOICE, 
            expiry=EXPIRY_DATE
        )

    elif ACTIVE_CATEGORY == "IRON_CONDOR":
        strategy = IronCondorStrategy(broker, risk)
        spot = IC_SPOT if IC_SPOT > 0 else broker.get_ltp(
            exchange="NSE", symbol="BANKNIFTY", token="99926009"
        )
        if spot == 0:
            logger.error("Could not determine BankNifty spot price — aborting.")
            sys.exit(1)
        result = strategy.check_and_trade(
            spot=spot, vix=VIX_VALUE, expiry=IC_EXPIRY, dry_run=DRY_RUN
        )

    elif ACTIVE_CATEGORY == "BREAKOUT":
        strategy = MorningBreakoutStrategy(broker, risk)
        candles  = broker.get_data(symbol=INDEX_CHOICE, interval="FIFTEEN_MINUTE")
        result   = strategy.get_signal(candles)

    else:
        logger.error(f"Unknown STRATEGY category: '{ACTIVE_CATEGORY}'.")
        sys.exit(1)

    # ── LOG RESULT ───────────────────────────────────────────────────────────
    clean = _clean_result(result)
    logger.info(f"📝 CYCLE RESULT:\n{json.dumps(clean, default=str, indent=2)}")

    # ── NEW: PERSISTENT JSON SAVE (For Streamlit Sync) ────────────────────────
    if clean.get("signal") in ("BUY_CALL", "BUY_PUT"):
        try:
            log_file = "trade_history.json"
            history = []
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    try:
                        history = json.load(f)
                    except:
                        history = []
            
            # Prepare entry to match the dashboard format
            new_entry = {
                "time": datetime.now(IST).strftime("%d-%b %H:%M:%S"),
                "index": INDEX_CHOICE,
                "signal": clean.get("signal"),
                "price": clean.get("price"),
                "sl": clean.get("stop_loss"),
                "target": clean.get("target"),
                "status": "OPEN",
                "pnl": 0.0,
                "mode": "PAPER-AUTO" if DRY_RUN else "LIVE-AUTO"
            }
            
            history.append(new_entry)
            
            with open(log_file, 'w') as f:
                json.dump(history, f, indent=2)
            logger.info("✅ Trade successfully logged to persistent JSON file.")
        except Exception as e:
            logger.error(f"Failed to write trade to JSON: {e}")

    # ── POSITION SUMMARY ─────────────────────────────────────────────────────
    positions = broker.get_positions()
    open_pos  = [p for p in positions if _safe_float(p.get("netqty", 0)) != 0]
    logger.info(f"📌 Open positions: {len(open_pos)}")
    for p in open_pos:
        upnl = _safe_float(p.get("unrealisedprofitandloss", 0))
        logger.info(
            f"  {p.get('tradingsymbol','')} | qty:{p.get('netqty','')} | P&L: ₹{upnl:,.0f}"
        )

    logger.info("=" * 60)
    logger.info("  QuantBengal Engine COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_bot()
