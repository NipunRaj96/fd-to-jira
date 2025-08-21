#!/usr/bin/env python3
"""
Fetch All Users from Freshdesk
==============================

This script fetches ALL contacts and agents from Freshdesk API without relying on ticket details.
"""

# Disable SSL warnings globally
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings()

import os
import json
import requests
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env')

# Disable SSL verification at environment level
os.environ['PYTHONHTTPSVERIFY'] = '0'

# Configuration
FRESHDESK_DOMAIN = os.getenv('FRESHDESK_DOMAIN')
FRESHDESK_API_KEY = os.getenv('FRESHDESK_API_KEY')

if not FRESHDESK_DOMAIN or not FRESHDESK_API_KEY:
    print("❌ Error: FRESHDESK_DOMAIN and FRESHDESK_API_KEY must be set in .env file")
    exit(1)

# API Configuration
BASE_URL = f"https://{FRESHDESK_DOMAIN}"
AUTH = (FRESHDESK_API_KEY, 'X')
HEADERS = {'Content-Type': 'application/json'}

def make_api_request(endpoint, params=None):
    """Make a rate-limited API request with error handling"""
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            auth=AUTH,
            headers=HEADERS,
            params=params,
            verify=False
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ API Error {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return None

def fetch_all_contacts():
    """Fetch all contacts from Freshdesk"""
    print("🔍 Fetching all contacts...")
    
    all_contacts = []
    page = 1
    per_page = 100
    
    while True:
        print(f"   📄 Fetching contacts page {page}...")
        
        params = {'page': page, 'per_page': per_page}
        response = make_api_request('/api/v2/contacts', params)
        
        if not response:
            print(f"   ❌ Failed to fetch contacts page {page}")
            break
            
        contacts = response if isinstance(response, list) else []
        
        if not contacts:
            print(f"   ✅ No more contacts found (page {page})")
            break
            
        all_contacts.extend(contacts)
        print(f"   ✅ Fetched {len(contacts)} contacts from page {page}")
        
        time.sleep(0.1)  # Rate limiting
        page += 1
    
    print(f"🎯 Total contacts fetched: {len(all_contacts)}")
    return all_contacts

def fetch_all_agents():
    """Fetch all agents from Freshdesk"""
    print("🔍 Fetching all agents...")
    
    all_agents = []
    page = 1
    per_page = 100
    
    while True:
        print(f"   📄 Fetching agents page {page}...")
        
        params = {'page': page, 'per_page': per_page}
        response = make_api_request('/api/v2/agents', params)
        
        if not response:
            print(f"   ❌ Failed to fetch agents page {page}")
            break
            
        agents = response if isinstance(response, list) else []
        
        if not agents:
            print(f"   ✅ No more agents found (page {page})")
            break
            
        all_agents.extend(agents)
        print(f"   ✅ Fetched {len(agents)} agents from page {page}")
        
        time.sleep(0.1)  # Rate limiting
        page += 1
    
    print(f"🎯 Total agents fetched: {len(all_agents)}")
    return all_agents

def save_data(contacts, agents):
    """Save all data to organized files"""
    print("💾 Saving data to files...")
    
    output_dir = 'user_directory'
    os.makedirs(output_dir, exist_ok=True)
    
    # Save raw data
    with open(f'{output_dir}/all_contacts.json', 'w') as f:
        json.dump(contacts, f, indent=2)
    
    with open(f'{output_dir}/all_agents.json', 'w') as f:
        json.dump(agents, f, indent=2)
    
    # Save summary
    summary = {
        'total_contacts': len(contacts),
        'total_agents': len(agents),
        'total_users': len(contacts) + len(agents),
        'active_contacts': len([c for c in contacts if c.get('active', False)]),
        'active_agents': len([a for a in agents if not a.get('deactivated', False)])
    }
    
    with open(f'{output_dir}/user_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"✅ Data saved to {output_dir}/ directory")
    return summary

def main():
    """Main execution function"""
    print("🚀 Starting Freshdesk User Directory Fetch")
    print("=" * 50)
    
    start_time = time.time()
    
    try:
        # Fetch all data
        contacts = fetch_all_contacts()
        agents = fetch_all_agents()
        
        if not contacts and not agents:
            print("❌ No data fetched. Check your API credentials and network connection.")
            return
        
        # Save everything
        summary = save_data(contacts, agents)
        
        # Display summary
        print("\n" + "=" * 50)
        print("📊 FETCH SUMMARY")
        print("=" * 50)
        print(f"👥 Total Contacts: {summary['total_contacts']}")
        print(f"👨‍💼 Total Agents: {summary['total_agents']}")
        print(f"🔢 Total Users: {summary['total_users']}")
        print(f"✅ Active Contacts: {summary['active_contacts']}")
        print(f"✅ Active Agents: {summary['active_agents']}")
        
        duration = time.time() - start_time
        print(f"\n⏱️  Total execution time: {duration:.2f} seconds")
        print(f"📁 Data saved to: user_directory/")
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
