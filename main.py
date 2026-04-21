import logging
from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy

# Setup logging to see output in GitHub Actions Console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_bot():
    logging.info("--- QUANTBENGAL ALGO ENGINE STARTED ---")
    
    # 1. Initialize Broker
    broker = IndianBrokerAPI()
    
    # 2. Initialize Strategy
    strategy = MomentumStrategy(broker)
    
    # 3. Analyze and Execute
    signal = strategy.check_momentum_breakout()
    strategy.execute_trade(signal)
    
    logging.info("--- QUANTBENGAL ALGO ENGINE FINISHED ---")

if __name__ == "__main__":
    run_bot()
