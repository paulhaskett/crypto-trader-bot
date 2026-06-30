#!/usr/bin/env python3
"""Database migration script for multi-level scale-in feature."""
import sqlite3
import os

def migrate_scale_in_columns():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'trades.db')
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return
    
    print(f"Running migrations on database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    columns = [
        ("scale_in_levels_triggered", "VARCHAR(50) DEFAULT ''"),
    ]
    
    for col_name, col_def in columns:
        cursor.execute("PRAGMA table_info(open_positions)")
        cols = [row[1] for row in cursor.fetchall()]
        if col_name not in cols:
            print(f"Adding column: {col_name}")
            cursor.execute(f"ALTER TABLE open_positions ADD COLUMN {col_name} {col_def}")
    
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate_scale_in_columns()
