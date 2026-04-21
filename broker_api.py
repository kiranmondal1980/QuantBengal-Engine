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
        ist = pytz.timezone('Asia/Kolkata')
        end_time = datetime.now(ist)
        start_time = end_time - timedelta(days=5)
        
        from_date_str = start_time.strftime("%Y-%m-%d 09:15")
        to_date_str = end_time.strftime("%Y-%m-%d 15:30")
        
        logging.info(f"Fetching data from {from_date_str} to {to_date_str}")
        
        # 26009 is the official Angel One token for Nifty Bank Index
        params = {
            "exchange": "NSE",
            "symboltoken": "26009", 
            "interval": "FIFTEEN_MINUTE", 
            "fromdate": from_date_str, 
            "todate": to_date_str
        }
        
        try:
            response = self.obj.getCandleData(params)
            # CRITICAL DEBUG LINE: This tells us exactly what Angel One thinks
            logging.info(f"Raw API Response: {response}") 
            
            if response and response.get('status') == True:
                return response.get('data', [])
            else:
                logging.error(f"API rejected the request. Reason: {response}")
                return []
        except Exception as e:
            logging.error(f"Failed to fetch data: {e}")
            return []

    def place_order(self, signal):
        logging.info(f"🚨 EXECUTING TRADE: {signal} 🚨")
        # Actual order placement logic will go here
