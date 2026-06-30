"""
Migration: Remove UNIQUE constraint from product_id in open_positions table.

SQLite doesn't support DROP CONSTRAINT, so we need to:
1. Create new table without the constraint
2. Copy data from old table
3. Drop old table
4. Rename new table
"""

from sqlalchemy import create_engine, text
import sqlite3
import os

# Database path
db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'trading_bot.db')
db_path = os.path.abspath(db_path)

print(f"Database path: {db_path}")

if not os.path.exists(db_path):
    print("Database not found, skipping migration")
    exit(0)

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if the constraint exists by looking at table info
    cursor.execute("PRAGMA table_info(open_positions)")
    columns = cursor.fetchall()
    print(f"Columns in open_positions: {len(columns)}")
    
    # Check for index on product_id
    cursor.execute("""
        SELECT name, sql FROM sqlite_master 
        WHERE type='index' AND tbl_name='open_positions' AND sql LIKE '%UNIQUE%'
    """)
    unique_indexes = cursor.fetchall()
    
    if not unique_indexes:
        print("No UNIQUE constraint found on open_positions.product_id, skipping")
        exit(0)
    
    print(f"Found UNIQUE indexes: {unique_indexes}")
    
    # Start transaction
    cursor.execute("BEGIN TRANSACTION")
    
    # 1. Create new table without UNIQUE constraint
    cursor.execute("""
        CREATE TABLE open_positions_new (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            position_id VARCHAR(50) NOT NULL,
            product_id VARCHAR(20) NOT NULL,
            side VARCHAR(10) NOT NULL,
            size FLOAT NOT NULL,
            entry_price FLOAT NOT NULL,
            current_price FLOAT,
            stop_loss_price FLOAT,
            signal_action VARCHAR(10) DEFAULT 'HOLD',
            signal_confidence FLOAT DEFAULT 0.0,
            status VARCHAR(20) DEFAULT 'open',
            position_type VARCHAR(20) DEFAULT 'normal',
            opened_at DATETIME,
            pnl FLOAT DEFAULT 0.0,
            trade_type VARCHAR(10) DEFAULT 'paper',
            peak_price FLOAT DEFAULT 0.0,
            scale_in_count INTEGER DEFAULT 0,
            last_scale_in_price FLOAT DEFAULT 0.0,
            last_scale_in_time DATETIME,
            total_scale_in_size FLOAT DEFAULT 0.0,
            weighted_entry_price FLOAT DEFAULT 0.0,
            scale_out_count INTEGER DEFAULT 0,
            scale_out_levels_triggered VARCHAR(50) DEFAULT '',
            last_scale_out_price FLOAT DEFAULT 0.0,
            last_scale_out_time DATETIME,
            remaining_size FLOAT DEFAULT 0.0
        )
    """)
    print("Created new table: open_positions_new")
    
    # 2. Copy all data from old table
    cursor.execute("""
        INSERT INTO open_positions_new 
        SELECT id, position_id, product_id, side, size, entry_price, 
               current_price, stop_loss_price, signal_action, signal_confidence,
               status, position_type, opened_at, pnl, trade_type, peak_price,
               scale_in_count, last_scale_in_price, last_scale_in_time,
               total_scale_in_size, weighted_entry_price, scale_out_count,
               scale_out_levels_triggered, last_scale_out_price,
               last_scale_out_time, remaining_size
        FROM open_positions
    """)
    print("Copied data to new table")
    
    # 3. Drop old table
    cursor.execute("DROP TABLE open_positions")
    print("Dropped old table")
    
    # 4. Rename new table
    cursor.execute("ALTER TABLE open_positions_new RENAME TO open_positions")
    print("Renamed new table to open_positions")
    
    # 5. Recreate indexes (without UNIQUE on product_id)
    cursor.execute("CREATE INDEX ix_open_positions_product_id ON open_positions(product_id)")
    cursor.execute("CREATE INDEX ix_open_positions_position_id ON open_positions(position_id)")
    print("Recreated indexes")
    
    # Commit transaction
    conn.commit()
    print("Migration completed successfully!")
    
except Exception as e:
    conn.rollback()
    print(f"Migration failed: {e}")
    raise
finally:
    conn.close()
