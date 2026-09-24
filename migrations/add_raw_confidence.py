#!/usr/bin/env python3
"""Add raw AI confidence and reconcile legacy prediction rows.

Existing signal_confidence remains the adjusted operational confidence.
Rows created before this migration cannot recover their original raw model
confidence, so raw_confidence is initialized to signal_confidence and marked
legacy by the migration output.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data' / 'trades.db'


def migrate():
    conn = sqlite3.connect(DB)
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(prediction_logs)')}
        if 'raw_confidence' not in columns:
            conn.execute('ALTER TABLE prediction_logs ADD COLUMN raw_confidence REAL')
            print('Added prediction_logs.raw_confidence')
        updated = conn.execute(
            'UPDATE prediction_logs SET raw_confidence = signal_confidence '
            'WHERE raw_confidence IS NULL'
        ).rowcount
        conn.commit()
        print(f'Backfilled {updated} legacy rows; future rows store raw confidence separately')
    finally:
        conn.close()


if __name__ == '__main__':
    migrate()
