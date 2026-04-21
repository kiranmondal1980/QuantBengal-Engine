from broker_api import IndianBrokerAPI
from strategy import MomentumStrategy
import logging

logging.basicConfig(level=logging.INFO)

def run_bot():
    try:
        broker = IndianBrokerAPI()
        strategy = MomentumStrategy(broker)
        strategy.check_and_trade()
    except Exception as e:
        logging.error(f"Bot failed: {e}")

if __name__ == "__main__":
    run_bot()
