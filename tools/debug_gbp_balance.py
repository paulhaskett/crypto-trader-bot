#!/usr/bin/env python3
"""
Debug script to check GBP balance extraction from different methods.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.coinbase_api import coinbase_api
from src.balance_manager import balance_manager
from src.currency_utils import currency_converter
from src.data_collector import data_collector

def debug_gbp_extraction():
    """Debug GBP balance extraction using different methods."""
    print("=== GBP Balance Extraction Debug ===\n")
    
    # Method 1: Balance Manager
    print("1. Balance Manager Method:")
    balance_status = balance_manager.check_gbp_balance()
    print(f"   GBP Balance: £{balance_status['gbp_balance']}")
    print(f"   Alert Level: {balance_status['alert_level']}")
    print(f"   Status Color: {balance_status['status_color']}")
    print()
    
    # Method 2: Direct Account Inspection
    print("2. Direct Account Inspection:")
    try:
        accounts = coinbase_api.get_accounts()
        print(f"   Total accounts: {len(accounts)}")
        
        gbp_found = False
        for i, account in enumerate(accounts):
            currency = account.get('currency', 'Unknown')
            available = account.get('available', 'Not found')
            balance = account.get('balance', 'Not found')
            
            print(f"   Account {i}: {currency}")
            print(f"     Available: {available}")
            print(f"     Balance: {balance}")
            
            if currency == 'GBP':
                gbp_found = True
                print(f"   *** GBP ACCOUNT FOUND ***")
                print(f"   Available field: {available}")
                print(f"   Balance field: {balance}")
                
                # Test float conversion
                try:
                    available_float = float(available) if available is not None else 0.0
                    balance_float = float(balance) if balance is not None else 0.0
                    print(f"   Available as float: £{available_float}")
                    print(f"   Balance as float: £{balance_float}")
                except (ValueError, TypeError) as e:
                    print(f"   Error converting to float: {e}")
        
        if not gbp_found:
            print("   *** NO GBP ACCOUNT FOUND ***")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # Method 3: Portfolio Debug Method
    print("3. Portfolio Debug Method:")
    try:
        accounts = coinbase_api.get_accounts()
        current_prices = data_collector.get_current_prices()
        
        gbp_balance = 0.0
        for account in accounts:
            currency = account['currency']
            balance = account['available']
            
            if currency == 'GBP':
                # Convert GBP to USD using current exchange rate
                gbp_to_usd_rate = currency_converter.get_exchange_rate('GBP', 'USD')
                value_usd = balance * gbp_to_usd_rate
                gbp_balance = balance
                print(f"   Found GBP: {balance}")
                print(f"   GBP to USD rate: {gbp_to_usd_rate}")
                print(f"   Value in USD: ${value_usd}")
                break
        
        print(f"   Final GBP balance: £{gbp_balance}")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # Method 4: Risk Manager Method
    print("4. Risk Manager Method:")
    try:
        from src.risk_manager import risk_manager
        risk_check = risk_manager.check_portfolio_risk(is_paper_trading=False)
        print(f"   GBP Balance: £{risk_check['gbp_balance']}")
        print(f"   GBP Status: {risk_check['gbp_status']}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n=== Debug Complete ===")

if __name__ == "__main__":
    debug_gbp_extraction()
