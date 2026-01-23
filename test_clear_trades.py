#!/usr/bin/env python3
"""Simple test for clear trades functionality"""

import sys
sys.path.append('/app/src')
from src.database import db_manager

print('=== Testing Clear Trades Function ===')

# Test adding some trades
print('Adding test trades...')
db_manager.save_trade('BTC-USD', 'buy', 0.001, 50000, 'test_001')
db_manager.save_trade('ETH-USD', 'sell', 0.01, 3000, 'test_002')
print('Added 2 test trades')

# Check current trades
trades = db_manager.get_trades()
print(f'Current trades: {len(trades)}')

# Test clearing
print('Clearing all trades...')
result = db_manager.clear_all_trades()
print(f'Cleared {result} trades')

# Verify cleared
trades_after = db_manager.get_trades()
print(f'Trades after clearing: {len(trades_after)}')

if len(trades_after) == 0:
    print('✅ Clear trades function working correctly!')
else:
    print('❌ Clear trades function failed')