"""
QuantBengal Engine — main.py  v5.0
GitHub Actions scheduler entry point.
Runs every 15 minutes during NSE market hours.
FIXES v5.0:
  - Cron: */15 3-9 (stops at 15:15 IST, not 16:29)
  - sys.exit(0) on market-closed (not silent return)
  - _clean_result() strips DataFrame before JSON logging
  - BANKNIFTY_SPOT env var support for Iron Condor
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

# ── CONFIG — all injected from GitHub Actions env / secrets ──────────────────
DRY_RUN         = os.environ.get("DRY_RUN", "true").lower() == "true"
ACTIVE_STRATEGY = os.environ.get("STRATEGY", "MOMENTUM").upper()
CAPITAL         = float(os.environ.get("CAPITAL", "200000"))
VIX_VALUE       = float(os.environ.get("VIX", "15.0"))
IC_EXPIRY       = os.environ.get("IC_EXPIRY", "23DEC")
IC_SPOT         = float(os.environ.get("BANKNIFTY_SPOT", "0"))


def is_market_hours() -> bool:
    """True only Mon–Fri 09:15–15:30 IST."""
    now = datetime.now(IST)
    if now.weekday() > 4:
        return False
    start = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    end   = now.replace(hour=15, minute=30, second=0, microsecond=0)
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
    logger.info(f"  QuantBengal Engine START | Strategy: {ACTIVE_STRATEGY}")
    logger.info(f"  DRY_RUN={DRY_RUN} | Capital=₹{CAPITAL:,.0f} | VIX={VIX_VALUE}")
    logger.info("=" * 60)

    if not is_market_hours():
        logger.info("Outside market hours (09:15–15:30 IST Mon–Fri) — engine idle.")
        sys.exit(0)

    # ── CONNECT ──────────────────────────────────────────────────────────────
    broker = IndianBrokerAPI()
    if not broker.connected:
        logger.error("Broker connection failed — aborting this run.")
        sys.exit(1)

    # ── RISK CHECK ───────────────────────────────────────────────────────────
    risk = RiskManager(capital=CAPITAL)
    pnl  = broker.get_pnl_summary()
    logger.info(
        f"P&L | Realised: ₹{pnl['realised']:,.0f}"
        f" | Unrealised: ₹{pnl['unrealised']:,.0f}"
        f" | Total: ₹{pnl['total']:,.0f}"
        f" | Open positions: {pnl['positions']}"
    )

    if not risk.check_daily_loss(pnl['total']):
        logger.error("Daily loss limit reached — halting for today.")
        sys.exit(0)

    # ── RUN SELECTED STRATEGY ─────────────────────────────────────────────
    result = {}

    if ACTIVE_STRATEGY == "MOMENTUM":
        strategy = MomentumStrategy(broker, risk)
        result   = strategy.check_and_trade(dry_run=DRY_RUN)

    elif ACTIVE_STRATEGY == "IRON_CONDOR":
        strategy = IronCondorStrategy(broker, risk)
        # Use injected spot price or fetch live LTP
        spot = IC_SPOT if IC_SPOT > 0 else broker.get_ltp(
            exchange="NSE", symbol="BANKNIFTY", token="99926009"
        )
        if spot == 0:
            logger.error("Could not determine BankNifty spot price — aborting.")
            sys.exit(1)
        result = strategy.check_and_trade(
            spot=spot, vix=VIX_VALUE, expiry=IC_EXPIRY, dry_run=DRY_RUN
        )

    elif ACTIVE_STRATEGY == "BREAKOUT":
        strategy = MorningBreakoutStrategy(broker, risk)
        candles  = broker.get_data(symbol="NIFTY", interval="FIFTEEN_MINUTE")
        result   = strategy.get_signal(candles)

    else:
        logger.error(f"Unknown STRATEGY value: '{ACTIVE_STRATEGY}'. Use MOMENTUM, IRON_CONDOR, or BREAKOUT.")
        sys.exit(1)

    # ── LOG RESULT ───────────────────────────────────────────────────────────
    clean = _clean_result(result)
    logger.info(f"RESULT:\n{json.dumps(clean, default=str, indent=2)}")

    # ── POSITION SUMMARY ─────────────────────────────────────────────────────
    positions = broker.get_positions()
    open_pos  = [p for p in positions if _safe_float(p.get("netqty", 0)) != 0]
    logger.info(f"Open positions after run: {len(open_pos)}")
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
