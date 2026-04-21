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
        logging.info("Fetching Real Market Data (Bypassing the 2026 clock error)...")
        
        # We must use real 2024 dates because Angel One does not have 2026 data
        from_date_str = "2024-05-14 09:15"
        to_date_str = "2024-05-20 15:30" 
        
        # Using State Bank of India (Token 3045) as it is 100% supported on all Angel One tiers
        params = {
            "exchange": "NSE",
            "symboltoken": "3045", 
            "interval": "FIFTEEN_MINUTE", 
            "fromdate": from_date_str, 
            "todate": to_date_str
        }
        
        try:
            response = self.obj.getCandleData(params)
            
            if response and response.get('status') == True:
                candles = response.get('data', [])
                if candles:
                    logging.info(f"SUCCESS: Received {len(candles)} real market candles.")
                    return candles
                else:
                    logging.error("API returned empty list. Dates may be a holiday/weekend.")
                    return []
            else:
                logging.error(f"API rejected request: {response}")
                return []
        except Exception as e:
            logging.error(f"Failed to fetch data: {e}")
            return []
    def place_order(self, signal):
        logging.info(f"🚨 EXECUTING TRADE: {signal} 🚨")
        # Actual order placement logic will go here
