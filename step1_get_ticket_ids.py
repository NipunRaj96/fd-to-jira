import requests
import csv
import json
import os
from dotenv import load_dotenv
import urllib3
from urllib3.exceptions import InsecureRequestWarning

# Disable SSL warnings for testing
urllib3.disable_warnings(InsecureRequestWarning)

# Load environment variables
load_dotenv()

# Get credentials from environment variables
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")
API_KEY = os.getenv("FRESHDESK_API_KEY")

# Validate that required environment variables are set
if not FRESHDESK_DOMAIN:
    raise ValueError("FRESHDESK_DOMAIN environment variable is not set")
if not API_KEY:
    raise ValueError("FRESHDESK_API_KEY environment variable is not set")

HEADERS = {
    "Content-Type": "application/json"
}

# Freshdesk status mappings
STATUS_MAP = {
    1: "Open",
    2: "Pending",
    3: "Resolved",
    4: "Closed",
    5: "Waiting on Customer",
    6: "Waiting on Third Party",
    7: "Waiting on Agent",
    8: "Waiting on Customer",
    9: "Waiting on Customer",
    10: "Waiting on Customer",
    11: "Waiting on Customer",
    12: "Waiting on Customer",
    13: "Waiting on Customer",
    14: "Waiting on Customer",
    15: "Waiting on Customer",
    16: "Waiting on Customer",
    17: "Waiting on Customer",
    18: "Waiting on Customer",
    19: "Waiting on Customer",
    20: "Waiting on Customer",
    21: "Waiting on Customer",
    22: "Waiting on Customer"
}

# Freshdesk priority mappings
PRIORITY_MAP = {
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Urgent"
}

# Freshdesk source mappings
SOURCE_MAP = {
    1: "Email",
    2: "Portal",
    3: "Phone",
    4: "Chat",
    5: "Mobihelp",
    6: "Feedback Widget",
    7: "Outbound Email",
    8: "E-commerce",
    9: "Bot",
    10: "Call",
    11: "Walk-in",
    12: "Social Media",
    13: "Other"
}

def map_status(status_code):
    """Convert numeric status to readable text"""
    return STATUS_MAP.get(status_code, f"Unknown({status_code})")

def map_priority(priority_code):
    """Convert numeric priority to readable text"""
    return PRIORITY_MAP.get(priority_code, f"Unknown({priority_code})")

def map_source(source_code):
    """Convert numeric source to readable text"""
    return SOURCE_MAP.get(source_code, f"Unknown({source_code})")

def get_agent_name(agent_id):
    """Get agent name from agent ID"""
    if not agent_id:
        return "Unassigned"
    
    try:
        url = f"https://{FRESHDESK_DOMAIN}/api/v2/agents/{agent_id}"
        response = requests.get(url, auth=(API_KEY, 'X'), headers=HEADERS, verify=False)
        if response.status_code == 200:
            agent_data = response.json()
            return agent_data.get('name', f"Agent {agent_id}")
        else:
            return f"Agent {agent_id}"
    except Exception:
        return f"Agent {agent_id}"

def get_ticket_ids():
    """Get all ticket IDs and save to CSV in the format expected by details_producer.py"""
    all_tickets = []
    page = 1
    per_page = 100  # Freshdesk API allows up to 100 per page
    
    print("Fetching all tickets from Freshdesk...")
    
    while True:
        url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets?page={page}&per_page={per_page}"
        response = requests.get(url, auth=(API_KEY, 'X'), headers=HEADERS, verify=False)
        
        if response.status_code != 200:
            print(f"Error fetching tickets on page {page}: {response.status_code}")
            break
        
        tickets = response.json()
        
        # If no tickets returned, we've reached the end
        if not tickets:
            print(f"No more tickets found on page {page}")
            break
        
        print(f"Page {page}: Found {len(tickets)} tickets")
        
        # Extract ticket IDs and basic info in the expected format
        for ticket in tickets:
            agent_id = ticket.get('agent_id')
            agent_name = get_agent_name(agent_id) if agent_id else "Unassigned"
            
            ticket_info = {
                'Ticket ID': ticket.get('id'),
                'Agent name': agent_name,
                'Status': map_status(ticket.get('status')),
                'Priority': map_priority(ticket.get('priority')),
                'Source': map_source(ticket.get('source'))
            }
            all_tickets.append(ticket_info)
            print(f"  Ticket ID: {ticket_info['Ticket ID']} - Agent: {ticket_info['Agent name']} - Status: {ticket_info['Status']}")
        
        # If we got fewer tickets than per_page, we've reached the end
        if len(tickets) < per_page:
            print(f"Reached end of tickets (got {len(tickets)} on page {page})")
            break
        
        page += 1
    
    print(f"\nTotal tickets found: {len(all_tickets)}")
    return all_tickets

def save_to_csv(ticket_ids, filename='tickets_total_tickets_enhanced.csv'):
    """Save ticket IDs to CSV file in the format expected by details_producer.py"""
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Ticket ID', 'Agent name', 'Status', 'Priority', 'Source']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for ticket in ticket_ids:
            writer.writerow(ticket)
    
    print(f"✅ Saved {len(ticket_ids)} ticket IDs to {filename}")
    print(f"📊 Format: {', '.join(fieldnames)}")

if __name__ == "__main__":
    print("Step 1: Getting all ticket IDs in the format expected by details_producer.py...")
    print("🔄 This will fetch agent names and map status/priority/source codes to readable text...")
    ticket_ids = get_ticket_ids()
    
    if ticket_ids:
        save_to_csv(ticket_ids)
        print(f"Successfully extracted {len(ticket_ids)} ticket IDs")
        print("🎯 CSV format now matches what details_producer.py expects!")
        print("📋 Data includes: Human-readable status, priority, source, and agent names!")
    else:
        print("No tickets found or error occurred") 