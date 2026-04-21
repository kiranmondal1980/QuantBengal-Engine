import pandas as pd
import logging

class MomentumStrategy:
    def __init__(self, broker):
        self.broker = broker
        self.symbol = "BANKNIFTY"

    def check_momentum_breakout(self):
        """
        Logic: If the current close is higher than the previous 4 candles' high,
        we have strong upward momentum. Buy ATM Call Option.
        """
        logging.info("Analyzing Bank Nifty Momentum...")
        
        # 1. Fetch Data
        data = self.broker.get_historical_data(self.symbol)
        closes = data["close"]
        highs = data["high"]

        current_close = closes[-1]
        previous_highs_max = max(highs[-5:-1]) # Highest high of last 4 candles

        # 2. Strategy Logic
        if current_close > previous_highs_max:
            logging.info(f"BREAKOUT DETECTED! Current Close ({current_close}) > Prev Highs ({previous_highs_max})")
            return "BUY_CALL"
        elif current_close < min(data["close"][-5:-1]):
            logging.info("BREAKDOWN DETECTED! Strong downward momentum.")
            return "BUY_PUT"
        else:
            logging.info("Market in range. No trade.")
            return "HOLD"

    def execute_trade(self, signal):
        if signal == "BUY_CALL":
            # In live market, you dynamically find the ATM strike (e.g., BANKNIFTY24MAY44500CE)
            option_symbol = "BANKNIFTY_ATM_CE" 
            self.broker.place_order(option_symbol, qty=15, transaction_type="BUY")
        
        elif signal == "BUY_PUT":
            option_symbol = "BANKNIFTY_ATM_PE"
            self.broker.place_order(option_symbol, qty=15, transaction_type="BUY")
