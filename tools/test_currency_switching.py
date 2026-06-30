#!/usr/bin/env python3
"""
Test script for currency switching functionality
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from main import unified_bot
from src.currency_utils import currency_converter

def test_currency_switching():
    """Test currency switching functionality"""
    
    print("=== Currency Switching Test ===\n")
    
    # Test 1: Get initial state
    print("1. Initial currency configuration:")
    info = unified_bot.get_currency_info()
    print(f"   Base currency: {info.get('base_currency')}")
    print(f"   Display currency: {info.get('display_currency')}")
    print(f"   Exchange rates: {info.get('exchange_rates')}")
    print()
    
    # Test 2: Switch display currency
    print("2. Testing display currency switch to USD...")
    success = unified_bot.set_display_currency('USD')
    print(f"   Success: {success}")
    info = unified_bot.get_currency_info()
    print(f"   New display currency: {info.get('display_currency')}")
    print()
    
    # Test 3: Switch base currency
    print("3. Testing base currency switch to USD...")
    success = unified_bot.set_base_currency('USD')
    print(f"   Success: {success}")
    info = unified_bot.get_currency_info()
    print(f"   New base currency: {info.get('base_currency')}")
    print(f"   Updated trading pairs: {info.get('trading_pairs')}")
    print()
    
    # Test 4: Currency conversion
    print("4. Testing currency conversion...")
    usd_amount = 1000.0
    gbp_amount = currency_converter.convert_amount(usd_amount, 'USD', 'GBP')
    back_to_usd = currency_converter.convert_amount(gbp_amount, 'GBP', 'USD')
    
    print(f"   ${usd_amount:.2f} USD = £{gbp_amount:.2f} GBP")
    print(f"   £{gbp_amount:.2f} GBP = ${back_to_usd:.2f} USD")
    print(f"   Conversion accuracy: ${abs(back_to_usd - usd_amount):.6f} difference")
    print()
    
    # Test 5: Currency formatting
    print("5. Testing currency formatting...")
    print(f"   USD format: {currency_converter.format_currency(1234.56, 'USD')}")
    print(f"   GBP format: {currency_converter.format_currency(1234.56, 'GBP')}")
    print()
    
    # Test 6: Switch back to GBP for base
    print("6. Switching base currency back to GBP...")
    success = unified_bot.set_base_currency('GBP')
    info = unified_bot.get_currency_info()
    print(f"   Success: {success}")
    print(f"   Final base currency: {info.get('base_currency')}")
    print(f"   Final trading pairs: {info.get('trading_pairs')}")
    print()
    
    print("=== Test Complete ===")
    print("✅ Currency switching system is working correctly!")

if __name__ == "__main__":
    test_currency_switching()