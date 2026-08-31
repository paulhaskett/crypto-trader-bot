"""Evaluate pending AI predictions by fetching current prices and
filling in actual outcomes. Runs hourly via cron.

For each PredictionLog whose timestamp is older than `horizon_hours` and
not yet evaluated:
  1. Fetch current consensus price for the pair
  2. Compare price_at_signal vs current price
  3. Mark as 'correct' or 'wrong' based on signal_action vs price movement
  4. Store result in DB for accuracy reporting
"""
import sys
import sqlite3
import logging
from datetime import datetime, timezone
sys.path.insert(0, '/app')

# Match the bot's logging setup so [PRED_EVAL] lines reach /app/logs/trading.log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/trading.log'),
        logging.StreamHandler(sys.stdout),
    ],
)

DB = '/app/data/trades.db'

def main():
    from src.database import db_manager

    pending = db_manager.get_pending_predictions(limit=50)
    if not pending:
        print("No pending predictions to evaluate.")
        return

    print(f"Found {len(pending)} pending predictions to evaluate.")

    # Build a quick price lookup from open_positions + market_data fallback
    # For each product, try the open_positions.current_price first; if not
    # open, fall back to market_data's latest candle close.
    price_cache = {}

    def get_price_now(product_id):
        if product_id in price_cache:
            return price_cache[product_id]
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        # Try open_positions first
        r = c.execute(
            "SELECT current_price FROM open_positions WHERE product_id=? AND status='open'",
            (product_id,)
        ).fetchone()
        if r:
            price_cache[product_id] = r['current_price']
            c.close()
            return r['current_price']
        # Fallback: latest market_data close
        r = c.execute(
            "SELECT close_price FROM market_data WHERE product_id=? ORDER BY timestamp DESC LIMIT 1",
            (product_id,)
        ).fetchone()
        if r:
            price_cache[product_id] = r['close_price']
            c.close()
            return r['close_price']
        c.close()
        return None

    evaluated_count = 0
    skipped_count = 0
    for pred in pending:
        pid = pred['product_id']
        price_now = get_price_now(pid)
        if price_now is None:
            skipped_count += 1
            continue
        ok = db_manager.evaluate_prediction(pred['id'], price_now)
        if ok:
            evaluated_count += 1

    print(f"Evaluated: {evaluated_count}, skipped (no price): {skipped_count}")


if __name__ == '__main__':
    main()