#!/usr/bin/env python3
"""
Debug trading state inconsistencies
"""

import requests
import json

def check_database_state():
    """Check what's stored in database vs what's in memory"""
    base_url = "http://localhost:8000"
    
    print("🔍 Database vs Memory State Analysis")
    print("=" * 50)
    
    # Check API status
    try:
        response = requests.get(f"{base_url}/api/status")
        api_status = response.json()
        
        print(f"📊 API Status:")
        print(f"   Trading Active (API): {api_status.get('trading_active', 'N/A')}")
        print(f"   Paper Trading: {api_status.get('paper_trading', 'N/A')}")
        print(f"   Active Positions: {api_status.get('active_positions', 'N/A')}")
        
    except Exception as e:
        print(f"❌ API Status check failed: {e}")
    
    # Check debug endpoints for database state
    try:
        response = requests.get(f"{base_url}/api/debug/context")
        debug_info = response.json()
        
        print(f"🔧 Debug Info:")
        print(f"   Display Currency: {debug_info.get('display_currency', 'N/A')}")
        print(f"   Paper Trading Setting: {debug_info.get('paper_trading', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Debug info check failed: {e}")
    
    # Test setting trading state directly
    try:
        print(f"\n🧪 Testing State Setting...")
        
        # Try to set trading active
        response = requests.post(f"{base_url}/api/control/start_trading", json={})
        print(f"   Start Response: {response.status_code} - {response.json()}")
        
        # Check if it actually took effect
        response = requests.get(f"{base_url}/api/status")
        new_status = response.json()
        
        print(f"   After start - Trading Active: {new_status.get('trading_active', 'N/A')}")
        
        # Try to set trading inactive
        response = requests.post(f"{base_url}/api/control/stop_trading", json={})
        print(f"   Stop Response: {response.status_code} - {response.json()}")
        
        # Check final state
        response = requests.get(f"{base_url}/api/status")
        final_status = response.json()
        
        print(f"   After stop - Trading Active: {final_status.get('trading_active', 'N/A')}")
        
    except Exception as e:
        print(f"❌ State setting test failed: {e}")

if __name__ == "__main__":
    check_database_state()