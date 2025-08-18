#!/usr/bin/env python3
"""
Test script to verify the integration of modular_extraction.py
"""

import os
import sys
from pathlib import Path

def test_imports():
    """Test if all required modules can be imported"""
    print("🧪 Testing imports...")
    
    try:
        from modular_extraction import MigrationCoordinator
        print("✅ MigrationCoordinator imported successfully")
        
        from extract_ticket_details import read_ticket_ids_from_csv
        print("✅ extract_ticket_details imported successfully")
        
        from download_attachments import download_attachments_batch
        print("✅ download_attachments imported successfully")
        
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_csv_reading():
    """Test if CSV file can be read"""
    print("\n📁 Testing CSV reading...")
    
    csv_file = "Sample Data from Design OCL - Sheet1.csv"
    if not Path(csv_file).exists():
        print(f"❌ CSV file not found: {csv_file}")
        return False
    
    try:
        from extract_ticket_details import read_ticket_ids_from_csv
        ticket_ids = read_ticket_ids_from_csv(csv_file)
        
        if ticket_ids:
            print(f"✅ Successfully read {len(ticket_ids)} ticket IDs from CSV")
            print(f"   First 5 ticket IDs: {ticket_ids[:5]}")
            return True
        else:
            print("❌ No ticket IDs found in CSV")
            return False
            
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return False

def test_coordinator_creation():
    """Test if MigrationCoordinator can be created"""
    print("\n🏗️ Testing MigrationCoordinator creation...")
    
    try:
        # Set test environment variables
        os.environ['FRESHDESK_DOMAIN'] = os.getenv('FRESHDESK_DOMAIN', 'test.freshdesk.com')
        os.environ['FRESHDESK_API_KEY'] = 'test_key'
        
        from modular_extraction import MigrationCoordinator
        coordinator = MigrationCoordinator()
        
        print("✅ MigrationCoordinator created successfully")
        print(f"   Output directories: {list(coordinator.output_dirs.keys())}")
        
        # Clean up dummy environment variables
        del os.environ['FRESHDESK_DOMAIN']
        del os.environ['FRESHDESK_API_KEY']
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating MigrationCoordinator: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Starting Integration Tests for Modular Extraction System")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_csv_reading,
        test_coordinator_creation
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Integration is working correctly.")
        print("\n📋 Next steps:")
        print("   1. Set your FRESHDESK_DOMAIN and FRESHDESK_API_KEY environment variables")
        print("   2. Run: python modular_extraction.py")
    else:
        print("❌ Some tests failed. Please check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 