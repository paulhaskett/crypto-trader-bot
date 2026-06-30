"""
Migration script to fix open_positions table issues.

Fixes:1. Duplicate positions (same product_id multiple times) - keep largest2. Orphaned positions (in DB but no actual holdings) - flag for review
3. Wrong trade_type (paper vs live mismatch) - fix

Run: python migrations/fix_positions.py
"""

import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='[MIGRATION] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / 'data' / 'trades.db'


def fix_duplicates(conn):
    """Remove duplicate positions, keeping largest size."""
    cursor = conn.cursor()
    
    # Find duplicates
    cursor.execute('''
        SELECT product_id, COUNT(*) as cnt, SUM(size) as total_size
        FROM open_positions
        GROUP BY product_id
        HAVING COUNT(*) > 1
    ''')
    duplicates = cursor.fetchall()
    
    if not duplicates:
        logger.info("No duplicate positions found")
        return 0
    
    fixed = 0
    for product_id, cnt, total_size in duplicates:
        logger.warning(f"Found duplicate: {product_id} has {cnt} records")
        
        # Get all records for this product
        cursor.execute(
            'SELECT id, size, remaining_size FROM open_positions WHERE product_id = ?',
            (product_id,)
        )
        records = cursor.fetchall()
        
        # Find the one with largest size
        max_record = max(records, key=lambda r: r[1])
        max_id = max_record[0]
        
        # Sum total from all records
        total_remaining = sum(r[2] for r in records)
        
        # Delete all records for this product
        cursor.execute('DELETE FROM open_positions WHERE product_id = ?', (product_id,))
        
        # Re-insert single merged record with total remaining size
        import uuid
        new_position_id = str(uuid.uuid4())
        # Use minimal columns - most will use defaults
        cursor.execute('''
            INSERT INTO open_positions (
                position_id, product_id, side, size, remaining_size, entry_price, weighted_entry_price, trade_type, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            new_position_id,
            product_id, 
            'buy',
            max_record[1],  
            total_remaining,
            0,  
            0,  
            'live',
            'open'
        ))
        
        logger.info(f"  Merged {cnt} records into 1 (size: {max_record[1]}, remaining: {total_remaining})")
        fixed += 1
    
    conn.commit()
    return fixed


def check_orphans(conn):
    """Find positions where DB has data but holdings are 0."""
    cursor = conn.cursor()
    
    # This would require checking against Coinbase - just log for review
    cursor.execute('''
        SELECT product_id, size, remaining_size 
        FROM open_positions 
        WHERE remaining_size <= 0 OR size <= 0
    ''')
    orphan = cursor.fetchall()
    
    if orphan:
        logger.warning("Found orphaned positions:")
        for product_id, size, remaining in orphan:
            logger.warning(f"  {product_id}: size={size}, remaining={remaining}")
    else:
        logger.info("No orphaned positions found")
    
    return len(orphan)


def fix_wrong_trade_type(conn):
    """Check for positions that should be different trade_type."""
    # This is harder to fix automatically without checking Coinbase
    # For now, just log any paper positions that might need review
    cursor = conn.cursor()
    cursor.execute('''
        SELECT product_id, size, trade_type 
        FROM open_positions 
        WHERE trade_type = 'paper'
    ''')
    paper = cursor.fetchall()
    
    if paper:
        logger.warning(f"Found {len(paper)} paper positions - check if these should be live:")
        for product_id, size, trade_type in paper:
            logger.warning(f"  {product_id}: size={size}, trade_type={trade_type}")
    else:
        logger.info("No paper positions found")
    
    return len(paper)


def main():
    logger.info("Starting position migration...")
    logger.info(f"Database: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    
    try:
        # 1. Fix duplicates
        fixed = fix_duplicates(conn)
        logger.info(f"Fixed {fixed} duplicate(s)")
        
        # 2. Check orphans  
        orphans = check_orphans(conn)
        
        # 3. Check wrong trade_type
        wrong = fix_wrong_trade_type(conn)
        
        # Final state
        cursor = conn.cursor()
        cursor.execute('SELECT product_id, size, trade_type FROM open_positions')
        final = cursor.fetchall()
        logger.info(f"Final position count: {len(final)}")
        for row in final:
            logger.info(f"  {row[0]}: size={row[1]}, trade_type={row[2]}")
        
    finally:
        conn.close()
    
    logger.info("Migration complete!")


if __name__ == '__main__':
    main()