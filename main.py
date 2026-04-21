import logging
from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_bot():
    logging.info("--- QUANTBENGAL ALGO ENGINE STARTED ---")
    broker = IndianBrokerAPI()
    strategy = MomentumStrategy(broker)
    
    # Capture the two values: signal (str) and price (float)
    signal, current_price = strategy.check_momentum_breakout()
    
    # Pass both to the execution function
    strategy.execute_trade(signal, current_price)
    
    logging.info("--- QUANTBENGAL ALGO ENGINE FINISHED ---")

if __name__ == "__main__":
    run_bot()
