#!/usr/bin/env python3
"""
Test script for web API endpoints
"""

import requests
import json
import time

def test_api_endpoints():
    """Test web API endpoints for currency switching"""
    
    base_url = "http://localhost:8000"
    
    print("=== Web API Test ===\n")
    
    # Test 1: Currency info endpoint
    print("1. Testing /api/currency/info endpoint...")
    try:
        response = requests.get(f"{base_url}/api/currency/info")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success: Base={data.get('base_currency')}, Display={data.get('display_currency')}")
            print(f"   Exchange rates: {data.get('exchange_rates')}")
        else:
            print(f"   ❌ Failed: Status {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("   ⚠️  Server not running - skipping web API tests")
        return
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Display currency change
    print("\n2. Testing display currency change to GBP...")
    try:
        response = requests.post(
            f"{base_url}/api/settings/display_currency",
            json={"value": "GBP"}
        )
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success: {data.get('message')}")
        else:
            print(f"   ❌ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Base currency change
    print("\n3. Testing base currency change to USD...")
    try:
        response = requests.post(
            f"{base_url}/api/settings/base_currency",
            json={"value": "USD"}
        )
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success: {data.get('message')}")
            print(f"   Updated pairs: {data.get('trading_pairs')}")
        else:
            print(f"   ❌ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 4: Exchange rate endpoint
    print("\n4. Testing /api/exchange_rate endpoint...")
    try:
        response = requests.get(f"{base_url}/api/exchange_rate")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success: Rate={data.get('rate')}, Source={data.get('source')}")
        else:
            print(f"   ❌ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n=== API Test Complete ===")

if __name__ == "__main__":
    test_api_endpoints()