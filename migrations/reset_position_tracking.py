"""
Migration: Reset Position Tracking
Date: 2026-03-19

Resets position tracking to fix drift between bot records and Coinbase.
- Clears stale trades table
- Syncs remaining_size with actual Coinbase balances
- Resets scale tracking fields
"""

import sys
sys.path.insert(0, '/app')

from src.database import db_manager
from src.coinbase_api import coinbase_api
from config.settings import settings
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def reset_position_tracking():
    print("=" * 60)
    print("MIGRATION: Reset Position Tracking")
    print("=" * 60)
    
    # Step 1: Clear all trades
    print("\nStep 1: Clearing trades table...")
    try:
        db_manager.clear_all_trades()
        print("  [OK] Trades table cleared")
    except Exception as e:
        print(f"  [FAIL] Failed to clear trades: {e}")
    
    # Step 2: Sync open_positions with Coinbase
    print("\nStep 2: Syncing open_positions with Coinbase...")
    
    positions = db_manager.load_open_positions()
    
    for product_id in settings.PRODUCT_IDS:
        currency = product_id.split('-')[0]
        actual_balance = coinbase_api.get_account_balance(currency)
        
        pos = positions.get(product_id, {})
        db_remaining = pos.get('remaining_size', pos.get('size', 0))
        db_size = pos.get('size', 0)
        
        drift = abs(actual_balance - db_remaining)
        drift_pct = (drift / db_remaining * 100) if db_remaining > 0 else 0
        
        print(f"\n  {product_id}:")
        print(f"    Actual Coinbase: {actual_balance:.8f}")
        print(f"    DB remaining:   {db_remaining:.8f}")
        print(f"    Drift: {drift:.8f} ({drift_pct:.1f}%)")
        
        if drift > 0.00000001:  # More than dust
            try:
                # Update existing position fields
                if pos.get('position_id'):
                    # Use raw SQL to update just the fields we need
                    from src.database import SessionLocal
                    session = SessionLocal()
                    try:
                        from src.database import OpenPosition
                        position = session.query(OpenPosition).filter(
                            OpenPosition.product_id == product_id
                        ).first()
                        
                        if position:
                            position.remaining_size = actual_balance
                            position.size = actual_balance if position.size == position.remaining_size else position.size
                            position.scale_in_count = 0
                            position.scale_in_levels_triggered = ''
                            position.scale_out_count = 0
                            position.scale_out_levels_triggered = ''
                            position.total_scale_in_size = 0.0
                            position.last_scale_in_time = None
                            position.last_scale_out_time = None
                            session.commit()
                            print(f"    [OK] Updated to {actual_balance:.8f}")
                        else:
                            print(f"    [SKIP] No DB record found")
                    except Exception as e:
                        session.rollback()
                        print(f"    [FAIL] DB update error: {e}")
                    finally:
                        session.close()
                else:
                    print(f"    [SKIP] No position_id in DB record")
            except Exception as e:
                print(f"    [FAIL] Failed to update: {e}")
        else:
            print(f"    [OK] Already in sync")
        
        # If Coinbase has 0 and DB has position, mark it closed
        if actual_balance < 0.00000001 and db_remaining > 0:
            print(f"    [!] Position closed on Coinbase, closing DB record...")
            try:
                db_manager.close_open_position_by_product(
                    product_id, 
                    0.0, 
                    0.0, 
                    'Closed: Coinbase balance is 0'
                )
                print(f"    [OK] DB position closed")
            except Exception as e:
                print(f"    [FAIL] Failed to close: {e}")
    
    # Step 3: Verify sync
    print("\n" + "=" * 60)
    print("Step 3: Verification")
    print("=" * 60)
    
    positions = db_manager.load_open_positions()
    total_portfolio = coinbase_api.get_account_balance('GBP')
    
    print(f"\nGBP Cash: £{total_portfolio:.2f}")
    print("\nOpen Positions:")
    
    for product_id in settings.PRODUCT_IDS:
        currency = product_id.split('-')[0]
        actual_balance = coinbase_api.get_account_balance(currency)
        
        pos = positions.get(product_id, {})
        db_remaining = pos.get('remaining_size', 0)
        
        if actual_balance > 0.00000001:
            total_portfolio += actual_balance * (pos.get('current_price', 0) or 0)
            status = "[SYNCED]" if abs(actual_balance - db_remaining) < 0.00000001 else "[DRIFT]"
            print(f"  {status} {product_id}: Coinbase={actual_balance:.8f}, DB={db_remaining:.8f}")
    
    print(f"\nTotal Portfolio Value: £{total_portfolio:.2f}")
    print("\n" + "=" * 60)
    print("Migration complete!")
    print("=" * 60)


if __name__ == "__main__":
    reset_position_tracking()
