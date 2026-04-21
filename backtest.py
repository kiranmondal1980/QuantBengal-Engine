import yfinance as yf
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

def run_backtest():
    print("--- QUANTBENGAL 30-DAY BACKTEST REPORT ---")
    
    # 1. Fetch 30 days of 15m data
    # Note: yfinance uses ^NSEI for Nifty 50
    data = yf.download("^NSEI", period="1mo", interval="15m")
    
    if data.empty:
        print("Error: Could not fetch market data.")
        return

    df = data.copy()
    
    # 2. Calculate Indicators
    df['ema_9'] = EMAIndicator(close=df['Close'], window=9).ema_indicator()
    df['ema_21'] = EMAIndicator(close=df['Close'], window=21).ema_indicator()
    df['rsi'] = RSIIndicator(close=df['Close'], window=14).rsi()
    
    # 3. Backtest Logic
    trades = []
    in_position = False
    entry_price = 0
    
    for i in range(1, len(df)):
        # Bullish Crossover (9 EMA crosses above 21 EMA + RSI > 55)
        if not in_position:
            if df['ema_9'].iloc[i-1] <= df['ema_21'].iloc[i-1] and \
               df['ema_9'].iloc[i] > df['ema_21'].iloc[i] and \
               df['rsi'].iloc[i] > 55:
                
                entry_price = df['Close'].iloc[i]
                trades.append({'type': 'BUY_CALL', 'entry_price': entry_price, 'entry_time': df.index[i]})
                in_position = True
                
        # Exit Logic: Cross back or RSI reversal
        elif in_position:
            if df['ema_9'].iloc[i] < df['ema_21'].iloc[i]:
                exit_price = df['Close'].iloc[i]
                trades[-1]['exit_price'] = exit_price
                trades[-1]['pnl'] = exit_price - entry_price
                in_position = False

    # 4. Summary Math
    trade_df = pd.DataFrame(trades)
    total_pnl = trade_df['pnl'].sum()
    win_rate = (trade_df['pnl'] > 0).mean() * 100
    
    print(f"Total Trades: {len(trade_df)}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total Index Points: {total_pnl:.2f}")
    print("\nLast 5 Trades Detail:")
    print(trade_df.tail(5))

if __name__ == "__main__":
    run_backtest()
