"""Evaluate pending AI predictions at their exact configured horizons.

Each prediction is compared with the nearest completed market-data candle at
``signal_timestamp + horizon_hours``. A current wallet price is never used as
a proxy for a historical target price.
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

    def get_price_at_horizon(prediction):
        """Return nearest completed candle at the prediction's target time."""
        target = datetime.fromisoformat(prediction['timestamp'].replace('Z', '+00:00'))
        if target.tzinfo is not None:
            target = target.replace(tzinfo=None)
        from datetime import timedelta
        target += timedelta(hours=int(prediction.get('horizon_hours') or 24))
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT timestamp, close_price FROM market_data "
            "WHERE product_id=? AND timestamp>=? "
            "ORDER BY timestamp ASC LIMIT 1",
            (prediction['product_id'], target.strftime('%Y-%m-%d %H:%M:%S'))
        ).fetchone()
        c.close()
        if not row:
            return None
        observed = datetime.fromisoformat(str(row['timestamp']).replace('Z', '+00:00'))
        if observed.tzinfo is not None:
            observed = observed.replace(tzinfo=None)
        # Do not grade a prediction against a candle that is too far beyond
        # its horizon; leave it pending for the next evaluator run.
        if (observed - target).total_seconds() > 2 * 3600:
            return None
        return float(row['close_price'])

    evaluated_count = 0
    skipped_count = 0
    for pred in pending:
        price_at_horizon = get_price_at_horizon(pred)
        if price_at_horizon is None:
            skipped_count += 1
            continue
        ok = db_manager.evaluate_prediction(pred['id'], price_at_horizon)
        if ok:
            evaluated_count += 1

    print(f"Evaluated: {evaluated_count}, skipped (no price): {skipped_count}")


if __name__ == '__main__':
    main()