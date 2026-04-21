import logging

class MomentumStrategy:
    def __init__(self, broker):
        self.broker = broker
        self.symbol = "BANKNIFTY.NS" 

    def check_momentum_breakout(self):
        logging.info("Analyzing REAL Bank Nifty Momentum...")
        data = self.broker.get_historical_data(self.symbol)
        
        if not data or len(data["close"]) < 5:
            logging.warning("Not enough data to run strategy.")
            return "HOLD", 0

        closes = data["close"]
        highs = data["high"]
        current_spot_price = data["latest_price"]
        current_close = closes[-1]
        previous_highs_max = max(highs[-5:-1])

        if current_close > previous_highs_max:
            logging.info(f"📈 BREAKOUT DETECTED! Current Close ({current_close}) > Prev Highs ({round(previous_highs_max, 2)})")
            return "BUY_CALL", current_spot_price
        elif current_close < min(closes[-5:-1]):
            logging.info("📉 BREAKDOWN DETECTED! Strong downward momentum.")
            return "BUY_PUT", current_spot_price
        else:
            logging.info("⚖️ Market is in range. No trade setup found.")
            return "HOLD", current_spot_price

    def execute_trade(self, signal, current_price):
        # Restored your detailed Option symbol naming
        if signal == "BUY_CALL":
            option_symbol = f"BANKNIFTY_ATM_CE (Spot: {current_price})" 
            self.broker.place_order(option_symbol, 15, "BUY", current_price)
        elif signal == "BUY_PUT":
            option_symbol = f"BANKNIFTY_ATM_PE (Spot: {current_price})"
            self.broker.place_order(option_symbol, 15, "BUY", current_price)
