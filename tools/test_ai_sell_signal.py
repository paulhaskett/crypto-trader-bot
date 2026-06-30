#!/usr/bin/env python3
"""
Test script for AI sell signal monitoring in positions.

This script tests the monitor_positions() function to ensure it properly
closes positions when AI generates SELL signals.
"""

import sys
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

sys.path.append('src')

from src.trading_engine import TradingEngine
from src.ai_model import AIModel
from src.coinbase_api import coinbase_api


def test_monitor_positions_with_ai_sell_signal():
    """Test that monitor_positions closes positions on AI SELL signal."""
    
    # Create a mock position
    test_position = {
        'product_id': 'BTC-GBP',
        'side': 'buy',
        'size': 0.001,
        'entry_price': 50000.0,
        'stop_loss_price': 47500.0,
        'take_profit_prices': [55000.0],
        'status': 'open',
        'created_at': datetime.now(),
        'entry_signal_confidence': 0.8
    }
    
    # Create trading engine instance
    engine = TradingEngine()
    
    # Add test position
    position_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    engine.active_positions[position_id] = test_position
    
    # Mock the data collector to return current prices
    with patch('src.trading_engine.data_collector.get_current_prices') as mock_prices:
        # Price is above stop loss and below take profit
        mock_prices.return_value = {'BTC-GBP': 51000.0}
        
        # Mock AI model to return SELL signal
        with patch('src.trading_engine.ai_model.get_signal') as mock_signal:
            mock_signal.return_value = {
                'action': 'SELL',
                'confidence': 0.75,
                'signal_strength': 0.8
            }
            
            # Mock coinbase_api to return sufficient balance
            with patch('src.trading_engine.coinbase_api.get_account_balance') as mock_balance:
                mock_balance.return_value = 0.002  # More than position size
                
                # Mock risk_manager.close_position
                with patch('src.trading_engine.risk_manager.close_position'):
                    # Run monitor_positions
                    closed_positions = engine.monitor_positions()
                    
                    # Verify position was closed
                    assert len(closed_positions) == 1, f"Expected 1 closed position, got {len(closed_positions)}"
                    assert closed_positions[0]['position_id'] == position_id
                    assert 'AI sell signal' in closed_positions[0]['exit_reason']
                    
                    print(f"✓ Test passed: Position closed on AI SELL signal")
                    print(f"  Exit reason: {closed_positions[0]['exit_reason']}")
                    print(f"  P&L: {closed_positions[0]['pnl']:.2f}")
                    
    return True


def test_monitor_positions_with_insufficient_balance():
    """Test that monitor_positions skips closing when balance is insufficient."""
    
    # Create a mock position
    test_position = {
        'product_id': 'BTC-GBP',
        'side': 'buy',
        'size': 0.001,
        'entry_price': 50000.0,
        'stop_loss_price': 47500.0,
        'take_profit_prices': [55000.0],
        'status': 'open',
        'created_at': datetime.now(),
        'entry_signal_confidence': 0.8
    }
    
    # Create trading engine instance
    engine = TradingEngine()
    
    # Add test position
    position_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    engine.active_positions[position_id] = test_position
    
    # Mock the data collector to return current prices
    with patch('src.trading_engine.data_collector.get_current_prices') as mock_prices:
        mock_prices.return_value = {'BTC-GBP': 51000.0}
        
        # Mock AI model to return SELL signal
        with patch('src.trading_engine.ai_model.get_signal') as mock_signal:
            mock_signal.return_value = {
                'action': 'SELL',
                'confidence': 0.75,
                'signal_strength': 0.8
            }
            
            # Mock coinbase_api to return INSUFFICIENT balance
            with patch('src.trading_engine.coinbase_api.get_account_balance') as mock_balance:
                mock_balance.return_value = 0.0005  # Less than position size (0.001)
                
                # Run monitor_positions
                closed_positions = engine.monitor_positions()
                    
                # Verify position was NOT closed due to insufficient balance
                assert len(closed_positions) == 0, f"Expected 0 closed positions (insufficient balance), got {len(closed_positions)}"
                
                # Verify position is still in active_positions
                assert position_id in engine.active_positions, "Position should still be active"
                assert engine.active_positions[position_id]['status'] == 'open'
                
                print(f"✓ Test passed: Position NOT closed due to insufficient balance")
                    
    return True


def test_monitor_positions_with_buy_signal():
    """Test that monitor_positions does NOT close on BUY signal for existing position."""
    
    # Create a mock position
    test_position = {
        'product_id': 'BTC-GBP',
        'side': 'buy',
        'size': 0.001,
        'entry_price': 50000.0,
        'stop_loss_price': 47500.0,
        'take_profit_prices': [55000.0],
        'status': 'open',
        'created_at': datetime.now(),
        'entry_signal_confidence': 0.8
    }
    
    # Create trading engine instance
    engine = TradingEngine()
    
    # Add test position
    position_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    engine.active_positions[position_id] = test_position
    
    # Mock the data collector to return current prices
    with patch('src.trading_engine.data_collector.get_current_prices') as mock_prices:
        mock_prices.return_value = {'BTC-GBP': 51000.0}
        
        # Mock AI model to return BUY signal (should NOT close)
        with patch('src.trading_engine.ai_model.get_signal') as mock_signal:
            mock_signal.return_value = {
                'action': 'BUY',
                'confidence': 0.75,
                'signal_strength': 0.8
            }
            
            # Run monitor_positions
            closed_positions = engine.monitor_positions()
                
            # Verify position was NOT closed
            assert len(closed_positions) == 0, f"Expected 0 closed positions (BUY signal), got {len(closed_positions)}"
            
            # Verify position is still in active_positions
            assert position_id in engine.active_positions, "Position should still be active"
            assert engine.active_positions[position_id]['status'] == 'open'
            
            print(f"✓ Test passed: Position NOT closed on BUY signal")
                
    return True


if __name__ == '__main__':
    print("Testing AI sell signal monitoring...")
    print("=" * 60)
    
    tests = [
        test_monitor_positions_with_ai_sell_signal,
        test_monitor_positions_with_insufficient_balance,
        test_monitor_positions_with_buy_signal
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            print(f"\nRunning: {test_func.__name__}")
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ Test failed: {test_func.__name__}")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 60)
    print(f"Tests completed: {passed} passed, {failed} failed")
    
    if failed > 0:
        sys.exit(1)
