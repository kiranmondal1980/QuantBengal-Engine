import os
import logging
from SmartApi.smartConnect import SmartConnect
import pyotp
import logzero # Add this import too!

class IndianBrokerAPI:
    def __init__(self):
        # Retrieve credentials from Environment Variables (GitHub Secrets)
        self.api_key = os.environ.get("BROKER_API_KEY")
        self.client_id = os.environ.get("CLIENT_ID")
        self.password = os.environ.get("PASSWORD")
        self.token = os.environ.get("TOTP_TOKEN")
        
        # Initialize connection
        self.obj = SmartConnect(api_key=self.api_key)
        
        # Authenticate
        totp = pyotp.TOTP(self.token).now()
        data = self.obj.generateSession(self.client_id, self.password, totp)
        
    def get_historical_data(self, symbol_token="35002"): # 35002 is BankNifty Index
        """
        Fetches data from Angel One SmartAPI
        """
        try:
            # Angel One requires a dictionary with exchange and symboltoken
            historicParam = {
                "exchange": "NSE",
                "symboltoken": symbol_token,
                "interval": "FIFTEEN_MINUTE",
                "fromdate": "2024-05-20 09:15", 
                "todate": "2024-05-21 15:30"
            }
            response = self.obj.getCandleData(historicParam)
            
            # response['data'] is a list of [timestamp, open, high, low, close, volume]
            candles = response['data']
            closes = [c[4] for c in candles]
            highs = [c[2] for c in candles]
            
            return {
                "close": closes,
                "high": highs,
                "latest_price": closes[-1]
            }
        except Exception as e:
            logging.error(f"Angel One API Error: {e}")
            return None
