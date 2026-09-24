#!/usr/bin/env python3
"""Reconcile historical filled-trade P&L from recorded fill prices and fees.

Uses FIFO cost basis, includes buy fees in cost, and deducts sell fees from
proceeds. Rows are changed only when both sides have a complete recorded fill.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data' / 'trades.db'


def reconcile():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        products = [r[0] for r in conn.execute(
            "SELECT DISTINCT product_id FROM trades WHERE status='filled'"
        )]
        updated = 0
        unreconciled = 0
        for product in products:
            lots = []
            rows = conn.execute(
                "SELECT id, side, size, price, fees FROM trades "
                "WHERE product_id=? AND status='filled' ORDER BY timestamp, id",
                (product,),
            ).fetchall()
            for row in rows:
                qty = float(row['size'] or 0.0)
                price = float(row['price'] or 0.0)
                fees = float(row['fees'] or 0.0)
                if qty <= 0 or price <= 0:
                    continue
                if row['side'].lower() == 'buy':
                    lots.append([qty, qty * price + fees])
                    continue
                if row['side'].lower() != 'sell':
                    continue
                remaining = qty
                cost_basis = 0.0
                while remaining > 1e-12 and lots:
                    lot_qty, lot_cost = lots[0]
                    used = min(remaining, lot_qty)
                    cost_basis += lot_cost * used / lot_qty
                    lot_qty -= used
                    lot_cost -= lot_cost * used / (lot_qty + used)
                    remaining -= used
                    if lot_qty <= 1e-12:
                        lots.pop(0)
                    else:
                        lots[0] = [lot_qty, lot_cost]
                if remaining > 1e-9:
                    unreconciled += 1
                    continue
                pnl = qty * price - fees - cost_basis
                conn.execute('UPDATE trades SET pnl=? WHERE id=?', (pnl, row['id']))
                updated += 1
        conn.commit()
        print(f'Reconciled {updated} sell fills; {unreconciled} lacked a complete buy cost basis')
    finally:
        conn.close()


if __name__ == '__main__':
    reconcile()
