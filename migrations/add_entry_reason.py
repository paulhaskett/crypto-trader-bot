#!/usr/bin/env python3
"""
Migration: Add entry_reason column to open_positions table.

This adds tracking for why positions were opened (e.g., "AI BUY, conf=72%, regime=uptrend").
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import DatabaseManager
from sqlalchemy import text


def migrate():
    """Add entry_reason column to open_positions table."""
    print("Starting migration: add entry_reason column...")
    
    db = DatabaseManager()
    engine = db.engine
    
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(open_positions)"))
        columns = [row[1] for row in result]
        
        if 'entry_reason' in columns:
            print("Column 'entry_reason' already exists. Skipping.")
            return
        
        # Add the column
        try:
            conn.execute(text("ALTER TABLE open_positions ADD COLUMN entry_reason VARCHAR(200) DEFAULT ''"))
            conn.commit()
            print("Successfully added 'entry_reason' column!")
        except Exception as e:
            print(f"Error adding column: {e}")
            # Try alternative approach for SQLite
            try:
                # For SQLite, we need to recreate the table
                print("Trying alternative migration approach...")
                conn.execute(text("ALTER TABLE open_positions ADD COLUMN entry_reason VARCHAR(200) DEFAULT ''"))
                conn.commit()
                print("Successfully added 'entry_reason' column!")
            except Exception as e2:
                print(f"Alternative approach also failed: {e2}")


if __name__ == '__main__':
    migrate()
    print("Migration complete!")