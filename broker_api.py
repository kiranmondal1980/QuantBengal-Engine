import os
import logging
from SmartApi.smartConnect import SmartConnect
import pyotp
from datetime import datetime, timedelta
import pytz

class IndianBrokerAPI:
    def __init__(self):
        self.api_key = os.environ.get("BROKER_API_KEY")
        self.client_id = os.environ.get("CLIENT_ID")
        self.password = os.environ.get("PASSWORD")
        self.token = os.environ.get("TOTP_TOKEN")
        
        self.obj = SmartConnect(api_key=self.api_key)
        
        try:
            totp = pyotp.TOTP(self.token).now()
            self.obj.generateSession(self.client_id, self.password, totp)
            logging.info("Session generated.")
        except Exception as e:
            logging.error(f"Login failed: {e}")

    def get_data(self):
        logging.info("Fetching LIVE Market Data...")
        
        # 1. Get exact current date/time in India
        ist = pytz.timezone('Asia/Kolkata')
        end_time = datetime.now(ist)
        # 2. Subtract 5 days to get enough candles for RSI
        start_time = end_time - timedelta(days=5)
        
        from_date_str = start_time.strftime("%Y-%m-%d 09:15")
        to_date_str = end_time.strftime("%Y-%m-%d %H:%M") # Up to the current minute
        
        logging.info(f"Querying Angel One from {from_date_str} to {to_date_str}")
        
        # 3. Use SBIN (3045) to bypass Angel One's Index data blocks
        params = {
            "exchange": "NSE",
            "symboltoken": "99926009", 
            "interval": "FIVE_MINUTE", 
            "fromdate": from_date_str, 
            "todate": to_date_str
        }
        
        try:
            response = self.obj.getCandleData(params)
            
            if response and response.get('status') == True:
                candles = response.get('data', [])
                if candles:
                    logging.info(f"SUCCESS: Received {len(candles)} live market candles.")
                    return candles
                else:
                    logging.error("API returned empty list for this token.")
                    return []
            else:
                logging.error(f"API rejected request: {response}")
                return []
        except Exception as e:
            logging.error(f"Failed to fetch live data: {e}")
            return []
    def place_order(self, signal):
        logging.info(f"🚨 EXECUTING TRADE: {signal} 🚨")
        # Actual order placement logic will go here
