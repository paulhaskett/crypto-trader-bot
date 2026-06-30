"""
Trading Loop - Standalone trading process.
This module runs the trading engine in a separate process.
Signals are generated fresh for trading decisions.
"""
import os
import sys
import time
import signal
import logging
from pathlib import Path

# Import from centralized cache_manager
from src.cache_manager import BASE_DIR, DATA_DIR, LOG_DIR, LAST_CYCLE_FILE

os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'trading.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class TradingProcess:
    def __init__(self):
        self.running = True
        self.last_cycle_time = time.time()
        self.cycle_count = 0
        
    def write_last_cycle_time(self):
        """Write last cycle time for API workers."""
        try:
            with open(LAST_CYCLE_FILE, 'w') as f:
                f.write(str(self.last_cycle_time))
        except Exception as e:
            logger.error(f"Error writing last cycle time: {e}")
    
    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def run_cycle(self):
        """Run a single trading cycle."""
        from src.trading_engine import trading_engine
        from src.ai_model import ai_model
        
        logger.info(f"=== Starting trading cycle #{self.cycle_count + 1} ===")
        cycle_start = time.time()
        
        try:
            results = trading_engine.run_trading_cycle()
            logger.info(f"Trading cycle #{self.cycle_count + 1} completed: {results}")
            
            # Update rolling accuracy for dynamic model weighting
            try:
                for product_id in ai_model.gbp_trading_pairs:
                    ai_model._update_rolling_accuracy(product_id)
                logger.info("Updated rolling accuracy for dynamic weighting")
            except Exception as e:
                logger.warning(f"Could not update rolling accuracy: {e}")
            
            self.last_cycle_time = time.time()
            try:
                self.write_last_cycle_time()
                logger.info(f"Updated last_cycle_time: {self.last_cycle_time}")
            except Exception as e:
                logger.error(f"Failed to write last_cycle_time: {e}")
            
            self.cycle_count += 1
            
            cycle_time = time.time() - cycle_start
            logger.info(f"=== Cycle #{self.cycle_count} completed in {cycle_time:.1f}s ===")
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def run(self):
        """Main loop."""
        from config.settings import settings
        from src.trading_engine import trading_engine
        
        logger.info("=" * 60)
        logger.info("TRADING PROCESS STARTING")
        logger.info("=" * 60)
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initial position sync
        try:
            logger.info("Running initial position sync...")
            trading_engine.initial_position_sync()
            logger.info("Initial position sync completed")
        except Exception as e:
            logger.error(f"Initial sync failed: {e}")
        
        # Run initial cycle
        logger.info("Running initial trading cycle...")
        try:
            self.run_cycle()
        except Exception as e:
            logger.error(f"Initial cycle failed: {e}")
        
        interval = settings.MARKET_CHECK_INTERVAL
        logger.info(f"Trading interval: {interval}s ({interval/60:.1f} minutes)")
        
        while self.running:
            try:
                elapsed = time.time() - self.last_cycle_time
                
                if elapsed < interval:
                    sleep_time = interval - elapsed
                    if sleep_time > 60:
                        logger.debug(f"Waiting {sleep_time:.0f}s for next cycle")
                    time.sleep(min(sleep_time, 60))
                    continue
                
                self.run_cycle()
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(60)
        
        logger.info("Trading process stopped")


if __name__ == "__main__":
    TradingProcess().run()
