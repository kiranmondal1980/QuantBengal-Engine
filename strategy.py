import pandas as pd
import logging
from ta.momentum import RSIIndicator

class MomentumStrategy:
    def __init__(self, broker):
        self.broker = broker

    def check_and_trade(self):
        candles = self.broker.get_data()
        
        # FIX: Check if we have enough data (at least 15 candles for RSI 14)
        if not candles or len(candles) < 15:
            logging.warning(f"Not enough data yet. Received {len(candles) if candles else 0} candles.")
            return
            
        # Convert to DataFrame
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # Calculate RSI
        rsi = RSIIndicator(close=df['close'], window=14).rsi()
        current_rsi = rsi.iloc[-1]
        
        logging.info(f"Current RSI: {round(current_rsi, 2)}")
        
        if current_rsi < 30:
            logging.info("RSI < 30 (Oversold). Triggering BUY_CALL.")
            self.broker.place_order("BUY_CALL")
        elif current_rsi > 70:
            logging.info("RSI > 70 (Overbought). Triggering BUY_PUT.")
            self.broker.place_order("BUY_PUT")
        else:
            logging.info("RSI is neutral. Waiting for better signal.")
