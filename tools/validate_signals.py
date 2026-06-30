#!/usr/bin/env python3
"""
Validate AI signals against actual price movements.

This script compares the signals in signal_cache.json with actual
price movements to determine if the AI predictions are accurate.
"""

import sys
import json
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_model import ai_model
from src.data_collector import data_collector
from src.cache_manager import read_signal_cache


def validate_signals(hours_ago: int = 12):
    """
    Validate signals against actual price movements.
    
    Args:
        hours_ago: How many hours ago to check signals (default 12h)
    
    Returns:
        List of validation results
    """
    results = []
    
    # Read cached signals
    signals = read_signal_cache()
    
    if not signals:
        print("No signals found in cache")
        return results
    
    print(f"Validating {len(signals)} signals...")
    print("=" * 60)
    
    for pair, data in signals.items():
        signal_time_str = data.get('timestamp', '')
        action = data.get('action', 'HOLD')
        confidence = data.get('confidence', 0.0)
        regime = data.get('regime', 'neutral')
        
        try:
            signal_time = datetime.fromisoformat(signal_time_str)
        except:
            print(f"{pair}: Invalid timestamp {signal_time_str}")
            continue
        
        # Calculate cutoff time (signal_time + hours_ago)
        cutoff_time = signal_time + timedelta(hours=hours_ago)
        current_time = datetime.now()
        
        # Only validate if enough time has passed
        if current_time < cutoff_time:
            hours_remaining = (cutoff_time - current_time).total_seconds() / 3600
            print(f"{pair}: Skipping (need {hours_remaining:.1f}h more)")
            continue
        
        # Get price data
        df = data_collector.collect_historical_data(pair, days=1)
        if df is None or len(df) < hours_ago + 1:
            print(f"{pair}: Insufficient data")
            continue
        
        # Find price at signal time
        pred_df = df[df.index <= signal_time]
        if pred_df.empty:
            print(f"{pair}: No data at signal time")
            continue
        
        price_at_signal = pred_df['close'].iloc[-1]
        
        # Get current price (or price at cutoff time)
        current_price = df['close'].iloc[-1]
        
        # Calculate price change
        price_change_pct = (current_price - price_at_signal) / price_at_signal * 100
        
        # Determine if signal was correct
        if action == 'BUY':
            correct = price_change_pct > 0
            expected_direction = 'UP'
        elif action == 'SELL':
            correct = price_change_pct < 0
            expected_direction = 'DOWN'
        else:  # HOLD
            correct = abs(price_change_pct) < 1.0  # Within 1%
            expected_direction = 'FLAT'
        
        result = {
            'pair': pair,
            'action': action,
            'confidence': f"{confidence:.1%}",
            'regime': regime,
            'signal_time': signal_time_str,
            'price_at_signal': f"£{price_at_signal:.2f}",
            'current_price': f"£{current_price:.2f}",
            'price_change': f"{price_change_pct:+.2f}%",
            'expected': expected_direction,
            'correct': correct
        }
        
        results.append(result)
        
        status = "✓ CORRECT" if correct else "✗ WRONG"
        print(f"{pair}: {action} (conf: {confidence:.1%}) → {price_change_pct:+.2f}% → {status}")
    
    return results


def generate_report(results):
    """Generate a summary report."""
    if not results:
        print("\nNo results to report")
        return
    
    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)
    
    total = len(results)
    correct = sum(1 for r in results if r['correct'])
    accuracy = correct / total if total > 0 else 0
    
    print(f"\nTotal Signals: {total}")
    print(f"Correct: {correct}")
    print(f"Accuracy: {accuracy:.1%}")
    
    # Breakdown by action
    print("\n--- By Action ---")
    for action in ['BUY', 'SELL', 'HOLD']:
        action_results = [r for r in results if r['action'] == action]
        if action_results:
            action_correct = sum(1 for r in action_results if r['correct'])
            action_accuracy = action_correct / len(action_results)
            print(f"{action}: {action_correct}/{len(action_results)} ({action_accuracy:.1%})")
    
    # Breakdown by regime
    print("\n--- By Regime ---")
    for regime in ['uptrend', 'downtrend', 'neutral']:
        regime_results = [r for r in results if r['regime'] == regime]
        if regime_results:
            regime_correct = sum(1 for r in regime_results if r['correct'])
            regime_accuracy = regime_correct / len(regime_results)
            print(f"{regime}: {regime_correct}/{len(regime_results)} ({regime_accuracy:.1%})")
    
    # List wrong predictions
    wrong = [r for r in results if not r['correct']]
    if wrong:
        print("\n--- Wrong Predictions ---")
        for r in wrong:
            print(f"{r['pair']}: {r['action']} at {r['price_at_signal']} → {r['current_price']} ({r['price_change']})")
    
    print("\n" + "=" * 60)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate AI signals against price movements')
    parser.add_argument('--hours', type=int, default=12, help='Hours since signal to validate (default: 12)')
    args = parser.parse_args()
    
    results = validate_signals(hours_ago=args.hours)
    generate_report(results)
    
    # Output JSON for programmatic use
    if results:
        output_file = 'data/signal_validation.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {output_file}")
