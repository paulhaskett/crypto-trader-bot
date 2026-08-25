"""Add underwater tracking columns to open_positions table.

v3.9: Adds columns to track when positions go below break-even, how
long they stay there, max drawdown, and recovery status. Used for
AI model feedback (positions still stay open under v2.9.2 mandate).

New columns:
  went_underwater_at      DATETIME nullable
  underwater_minutes_total INTEGER default 0
  underwater_max_drawdown  FLOAT default 0.0
  recovered_at            DATETIME nullable
  eventual_outcome        VARCHAR(20) default ''

Safe to run multiple times — uses IF NOT EXISTS-equivalent checks.
"""
import sqlite3
import sys

DB = '/app/data/trades.db'

def migrate():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    new_columns = [
        ('went_underwater_at', 'DATETIME'),
        ('underwater_minutes_total', 'INTEGER DEFAULT 0'),
        ('underwater_max_drawdown', 'FLOAT DEFAULT 0.0'),
        ('recovered_at', 'DATETIME'),
        ('eventual_outcome', "VARCHAR(20) DEFAULT ''"),
    ]

    # Get existing columns
    existing = {row[1] for row in c.execute("PRAGMA table_info(open_positions)")}

    added = 0
    skipped = 0
    for col_name, col_type in new_columns:
        if col_name in existing:
            print(f"  SKIP: {col_name} already exists")
            skipped += 1
        else:
            sql = f"ALTER TABLE open_positions ADD COLUMN {col_name} {col_type}"
            try:
                c.execute(sql)
                print(f"  ADD:  {col_name} {col_type}")
                added += 1
            except Exception as e:
                print(f"  FAIL: {col_name} -> {e}")

    conn.commit()
    conn.close()
    print(f"\nMigration complete: {added} added, {skipped} already present")

if __name__ == '__main__':
    migrate()