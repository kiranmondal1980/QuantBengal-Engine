import os
import logging
import yfinance as yf

class IndianBrokerAPI:
    def __init__(self):
        self.api_key = os.environ.get("BROKER_API_KEY")
        if not self.api_key:
            logging.warning("API Keys not found. Running in REAL-MARKET PAPER TRADING mode.")

    def get_historical_data(self, symbol="BANKNIFTY.NS", timeframe="15m"):
        logging.info(f"Fetching market data for {symbol}...")
        try:
            data = yf.download(symbol, period="5d", interval=timeframe, progress=False)
            
            # IF DATA IS EMPTY (Market Closed), return Mock Data so the Dashboard works
            if data.empty:
                logging.warning("Market closed. Returning MOCK data for UI testing.")
                return {
                    "close": [44000, 44100, 44200, 44300, 44400],
                    "high": [44050, 44150, 44250, 44350, 44450],
                    "latest_price": 44400
                }
            
            # Otherwise return Real Data
            return {
                "close": data['Close'].tolist(),
                "high": data['High'].tolist(),
                "latest_price": round(float(data['Close'].iloc[-1]), 2)
            }
        except Exception as e:
            logging.error(f"Error: {e}")
            return None

    def place_order(self, symbol, qty, transaction_type, current_price, order_type="MARKET"):
        # Restored your detailed logging format
        logging.info("==================================================")
        logging.info(f"🚨 PAPER TRADE EXECUTED: {transaction_type} 🚨")
        logging.info(f"Instrument: {symbol}")
        logging.info(f"Quantity: {qty}")
        logging.info(f"Order Type: {order_type}")
        logging.info(f"Market Spot Price at Execution: {current_price}")
        logging.info("==================================================")
        return {"status": "paper_success", "price": current_price}
