import pandas as pd
import logging
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

class MomentumStrategy:
    def __init__(self, broker):
        self.broker = broker

    def check_and_trade(self):
        logging.info("Analyzing Bank Nifty Momentum Strategy (9/21 EMA + RSI)...")
        candles = self.broker.get_data()
        
        if not candles or len(candles) < 30:
            logging.warning("Not enough data to calculate EMA/RSI. Waiting...")
            return
            
        # 1. Convert to DataFrame
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # 2. Calculate Indicators
        df['ema_9'] = EMAIndicator(close=df['close'], window=9).ema_indicator()
        df['ema_21'] = EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['rsi'] = RSIIndicator(close=df['close'], window=14).rsi()
        
        # 3. Get the latest completed candle data
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        
        logging.info(f"Current Price: {latest['close']} | 9 EMA: {round(latest['ema_9'],2)} | 21 EMA: {round(latest['ema_21'],2)} | RSI: {round(latest['rsi'],2)}")
        
        # 4. TRADING LOGIC
        # Condition 1: Bullish Crossover (9 crosses above 21) AND RSI shows strength (> 55)
        if previous['ema_9'] <= previous['ema_21'] and latest['ema_9'] > latest['ema_21'] and latest['rsi'] > 55:
            logging.info("🟢 STRONG BUY SIGNAL: 9 EMA crossed above 21 EMA. Executing BUY_CALL.")
            self.broker.place_order("BUY_CALL")
            
        # Condition 2: Bearish Crossover (9 crosses below 21) AND RSI shows weakness (< 45)
        elif previous['ema_9'] >= previous['ema_21'] and latest['ema_9'] < latest['ema_21'] and latest['rsi'] < 45:
            logging.info("🔴 STRONG SELL SIGNAL: 9 EMA crossed below 21 EMA. Executing BUY_PUT.")
            self.broker.place_order("BUY_PUT")
            
        else:
            logging.info("⚖️ No momentum crossover detected. Holding position.")
