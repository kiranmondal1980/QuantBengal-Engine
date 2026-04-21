import os
import logging
import yfinance as yf

class IndianBrokerAPI:
    def __init__(self):
        # Keys for future real-money integration
        self.api_key = os.environ.get("BROKER_API_KEY")
        if not self.api_key:
            logging.warning("API Keys not found. Running in REAL-MARKET PAPER TRADING mode.")

    def get_historical_data(self, symbol="^NSEBANK", timeframe="15m"):
        """
        Fetches LIVE market data using Yahoo Finance.
        ^NSEBANK is the ticker for Nifty Bank.
        """
        logging.info(f"Fetching LIVE {timeframe} market data for {symbol}...")
        
        try:
            # Download the last 5 days of 15-minute candles
            data = yf.download(symbol, period="5d", interval=timeframe, progress=False)
            
            if data.empty:
                logging.error("Market data empty. Is the market closed or symbol wrong?")
                return None
            
            # Convert Pandas columns to Python lists
            closes = data['Close'].tolist()
            highs = data['High'].tolist()
            
            logging.info(f"Successfully fetched {len(closes)} live market candles.")
            logging.info(f"Latest Market Close Price: {round(closes[-1], 2)}")
            
            return {
                "close": closes,
                "high": highs,
                "latest_price": round(closes[-1], 2)
            }
        except Exception as e:
            logging.error(f"Failed to fetch real market data: {e}")
            return None

    def place_order(self, symbol, qty, transaction_type, current_price, order_type="MARKET"):
        """
        PAPER TRADING EXECUTION
        """
        logging.info("==================================================")
        logging.info(f"🚨 PAPER TRADE EXECUTED: {transaction_type} 🚨")
        logging.info(f"Instrument: {symbol}")
        logging.info(f"Quantity: {qty}")
        logging.info(f"Market Spot Price at Execution: {current_price}")
        logging.info("==================================================")
        return {"status": "paper_success", "price": current_price}
