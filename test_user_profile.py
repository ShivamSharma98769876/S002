#!/usr/bin/env python3
"""
Test script to check user profile API
"""

import sys
from src.config.config_manager import ConfigManager
from src.api.kite_client import KiteClient

def test_user_profile():
    print("=" * 80)
    print("Testing User Profile API")
    print("=" * 80)
    
    try:
        config_manager = ConfigManager()
        kite_client = KiteClient(config_manager)
        
        # Check if authenticated
        if not kite_client.is_authenticated():
            print("\n[ERROR] Not authenticated with Kite API")
            print("Please authenticate first using the dashboard")
            return
        
        print("\n[OK] Kite client is authenticated")
        
        # Get profile
        try:
            profile = kite_client.get_profile()
            print("\n[OK] Profile fetched successfully")
            print("\nProfile Data:")
            print("-" * 80)
            for key, value in profile.items():
                print(f"  {key}: {value}")
            
            # Extract user info
            user_id = (
                profile.get('user_id') or 
                profile.get('userid') or 
                profile.get('userID') or 
                'N/A'
            )
            
            user_name = (
                profile.get('user_name') or 
                profile.get('username') or 
                profile.get('name') or 
                profile.get('userName') or 
                'N/A'
            )
            
            print("\n" + "-" * 80)
            print("Extracted Information:")
            print(f"  User ID: {user_id}")
            print(f"  User Name: {user_name}")
            
        except Exception as e:
            print(f"\n[ERROR] Failed to fetch profile: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_user_profile()

