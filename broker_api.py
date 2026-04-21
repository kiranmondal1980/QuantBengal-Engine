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
        logging.info("Running PROOF OF LIFE test with SBIN...")
        
        # 3045 is the token for State Bank of India (SBIN)
        # We use a hardcoded date from early May to guarantee market was open
        params = {
            "exchange": "NSE",
            "symboltoken": "3045", 
            "interval": "FIFTEEN_MINUTE", 
            "fromdate": "2024-05-02 09:15", 
            "todate": "2024-05-10 15:30"
        }
        
        try:
            response = self.obj.getCandleData(params)
            logging.info(f"Raw API Response: {response}") 
            
            if response and response.get('status') == True:
                candles = response.get('data', [])
                logging.info(f"SUCCESS: Received {len(candles)} candles.")
                return candles
            else:
                logging.error(f"API rejected the request. Reason: {response}")
                return []
        except Exception as e:
            logging.error(f"Failed to fetch data: {e}")
            return []

    def place_order(self, signal):
        logging.info(f"🚨 EXECUTING TRADE: {signal} 🚨")
        # Actual order placement logic will go here
