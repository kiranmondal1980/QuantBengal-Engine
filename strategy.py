import pandas as pd
from ta.momentum import RSIIndicator

class MomentumStrategy:
    def __init__(self, broker):
        self.broker = broker

    def check_and_trade(self):
        candles = self.broker.get_data()
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # Calculate RSI
        rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
        
        if rsi < 30:
            self.broker.place_order("BUY_CALL")
        elif rsi > 70:
            self.broker.place_order("BUY_PUT")
