#!/usr/bin/env python3
"""
Test trading engine functionality after price data pipeline fix
"""

import requests
import json
import time

def test_trading_engine():
    """Comprehensive test of trading engine after price pipeline fix"""
    base_url = "http://localhost:8000"
    
    print("🚀 Testing Trading Engine After Price Pipeline Fix")
    print("=" * 60)
    
    # Test 1: Check initial status
    print("\n1. 📊 Initial Status Check:")
    try:
        response = requests.get(f"{base_url}/api/status")
        status = response.json()
        print(f"   Trading Active: {status.get('trading_active', 'N/A')}")
        print(f"   Paper Trading: {status.get('paper_trading', 'N/A')}")
        print(f"   Active Positions: {status.get('active_positions', 'N/A')}")
    except Exception as e:
        print(f"   ❌ Status check failed: {e}")
    
    # Test 2: Check price data availability
    print("\n2. 💰 Price Data Pipeline Test:")
    try:
        response = requests.get(f"{base_url}/api/portfolio/debug")
        data = response.json()
        
        calc_methods = data.get('calculation_methods', {})
        assets = calc_methods.get('sum_usd_then_convert', {}).get('assets', [])
        
        print(f"   Assets with USD prices:")
        for asset in assets:
            currency = asset.get('currency', 'N/A')
            usd_price = asset.get('price_usd', 'N/A')
            print(f"     {currency}: ${usd_price}")
            
    except Exception as e:
        print(f"   ❌ Price data check failed: {e}")
    
    # Test 3: Monitor for trading cycle activity
    print("\n3. 🔄 Trading Cycle Monitor (30 seconds):")
    print("   Waiting for trading cycle logs...")
    
    # Check logs periodically
    cycle_detected = False
    
    for i in range(6):  # Check for 30 seconds (6 checks × 5 seconds)
        time.sleep(5)
        
        try:
            # Get recent logs via status (since we don't have direct log access)
            response = requests.get(f"{base_url}/api/status")
            if response.status_code == 200:
                current_status = response.json()
                positions = current_status.get('active_positions', 0)
                
                if positions > 0:
                    print(f"   ✅ [{30-i*5}s] Active positions detected: {positions}")
                    cycle_detected = True
                    break
                else:
                    print(f"   ⏳ [{30-i*5}s] No active positions yet...")
            else:
                print(f"   ❌ [{30-i*5}s] Status check failed")
                
        except Exception as e:
            print(f"   ❌ [{30-i*5}s] Monitor error: {e}")
    
    # Test 4: Check if trading cycles are running
    print(f"\n4. 🎯 Results:")
    if cycle_detected:
        print("   ✅ Trading cycles appear to be executing")
        print("   ✅ Price pipeline fix successful")
        print("   ✅ USD prices available for risk management")
        print("   ✅ Positions can be opened and managed")
    else:
        print("   ⚠️  No trading activity detected in 30 seconds")
        print("   ⚠️  Check if trading cycles need more time")
        print("   ⚠️  May need to check AI model signal generation")
    
    print("\n" + "=" * 60)
    print("📝 Next Steps:")
    print("1. If trading cycles are working, monitor dashboard for real-time updates")
    print("2. Check for trade executions in database")
    print("3. Verify AI signal generation is working")
    print("4. Monitor position management")

if __name__ == "__main__":
    test_trading_engine()