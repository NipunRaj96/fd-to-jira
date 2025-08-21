# extract_ticket_details.py - Consolidated Single API Call Approach
# This script uses a single API call per ticket: ?include=conversations
# All data (ticket details, conversations, attachments) is stored in one JSON file per ticket

# Disable SSL warnings globally
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings()

import requests
import csv
import json
import time
import os
import logging
import gzip
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Load environment variables from current directory
load_dotenv('.env')

# Disable SSL verification at environment level
os.environ['PYTHONHTTPSVERIFY'] = '0'

# Get credentials from environment variables
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")
API_KEY = os.getenv("FRESHDESK_API_KEY")
FRESH = os.getenv("FRESH", "n").lower()  # Default to 'n' if not set

# Validate that required environment variables are set
if not FRESHDESK_DOMAIN:
    raise ValueError("FRESHDESK_DOMAIN environment variable is not set")
if not API_KEY:
    raise ValueError("FRESHDESK_API_KEY environment variable is not set")

# Configuration for large-scale migration (40K tickets)
CONFIG = {
    'batch_size': 100,  # Process 100 tickets per batch
    'delay_between_requests': 0.1,  # 1000 requests/hour = 3.6 seconds between requests
    'delay_between_batches': 10,  # Additional delay between batches
    'max_retries': 3,
    'save_interval': 10,  # Save progress every 10 batches
    'rate_limit_requests_per_hour': 10000
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('step2_migration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log the API strategy based on FRESH environment variable
logger.info(f"🔧 API Strategy: FRESH={FRESH} (y=active first, n=archived first)")

def print_usage_info():
    """Print information about the consolidated API approach"""
    print("\n" + "="*60)
    print("🔄 CONSOLIDATED API APPROACH")
    print("="*60)
    print("✅ Single API call per ticket: ?include=conversations")
    print("✅ All data in one JSON file per ticket")
    print("✅ 50% fewer API calls compared to separate calls")
    print("✅ Complete data includes:")
    print("   • Ticket details")
    print("   • All conversations")
    print("   • Ticket-level attachments")
    print("   • Conversation attachments")
    print("\n📁 Output:")
    print("   • Directory: complete_ticket_data/")
    print("   • Format: ticket_{id}_complete.json")
    print("   • Each file contains ALL data for that ticket")
    print("="*60 + "\n")

# Setup session with retry strategy and connection pooling
def setup_session_with_retry():
    """Create a requests session with retry strategy and connection pooling for high concurrency"""
    session = requests.Session()
    
    # Enhanced retry strategy
    retry_strategy = Retry(
        total=CONFIG['max_retries'],
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
    )
    
    # Enhanced connection pooling adapter
    adapter = HTTPAdapter(
        pool_connections=50,      # Number of connection pools to cache
        pool_maxsize=100,         # Maximum number of connections in each pool
        max_retries=retry_strategy,
        pool_block=False          # Don't block when pool is full
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set session-level timeouts
    session.timeout = (30, 60)  # (connect_timeout, read_timeout)
    
    # Disable SSL verification for corporate network compatibility
    session.verify = False
    
    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    return session

# Global session with enhanced connection pooling
session = setup_session_with_retry()

HEADERS = {
    "Content-Type": "application/json"
}

def get_connection_pool_status():
    """Get current connection pool status for monitoring"""
    try:
        adapter = session.get_adapter('https://')
        if hasattr(adapter, 'poolmanager'):
            pool = adapter.poolmanager.connection_from_url('https://' + FRESHDESK_DOMAIN)
            return {
                'pool_size': 'active',  # Pool is active
                'available': 'monitoring_enabled'
            }
    except Exception as e:
        pass
    return {'pool_size': 'unknown', 'available': 'unknown'}

def cleanup_connections():
    """Clean up and close all connections in the pool"""
    try:
        session.close()
        logger.info("✅ All connections cleaned up successfully")
    except Exception as e:
        logger.warning(f"Warning during connection cleanup: {e}")

def rate_limited_request(url, auth=None, **kwargs):
    """Make a rate-limited request with proper delays and connection pool monitoring"""
    try:
        # Log connection pool status periodically
        if hasattr(rate_limited_request, 'request_count'):
            rate_limited_request.request_count += 1
        else:
            rate_limited_request.request_count = 1
        
        if rate_limited_request.request_count % 50 == 0:  # Log every 50 requests
            pool_status = get_connection_pool_status()
            logger.info(f"Connection pool status: {pool_status}")
        
        # Ensure SSL verification is disabled for this request
        kwargs['verify'] = False
        
        response = session.get(url, auth=auth, headers=HEADERS, **kwargs)
        
        # Handle rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return rate_limited_request(url, auth=auth, **kwargs)
        
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}")
        # Log connection pool status on error
        pool_status = get_connection_pool_status()
        logger.error(f"Connection pool status on error: {pool_status}")
        raise

def save_progress(processed_tickets, batch_number, filename="step2_progress.json"):
    """Save migration progress to resume later"""
    progress_data = {
        'processed_tickets': processed_tickets,
        'batch_number': batch_number,
        'timestamp': datetime.now().isoformat(),
        'total_processed': len(processed_tickets)
    }
    
    with open(filename, 'w') as f:
        json.dump(progress_data, f, indent=2)
    
    logger.info(f"Progress saved: {len(processed_tickets)} tickets processed")

def load_progress(filename="step2_progress.json"):
    """Load migration progress to resume"""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return None

def save_batch_json(tickets, batch_number, base_dir="batches"):
    """Save a batch of tickets to compressed JSON"""
    Path(base_dir).mkdir(exist_ok=True)
    
    filename = f"{base_dir}/batch_{batch_number:03d}.json.gz"
    with gzip.open(filename, 'wt', encoding='utf-8') as f:
        json.dump(tickets, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Batch {batch_number} saved: {len(tickets)} tickets to {filename}")

def read_ticket_ids_from_csv(filename=None):
    """Read ticket IDs from CSV file"""
    if filename is None:
        filename = os.getenv('TICKET_IDS_CSV_FILE')
    
    ticket_ids = []
    logger.info(f"📖 Reading ticket IDs from {filename}")
    try:
        with open(filename, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                ticket_ids.append(int(row['Ticket ID']))
        
        logger.info(f"✅ Read {len(ticket_ids)} ticket IDs from {filename}")
        return ticket_ids
    except FileNotFoundError:
        logger.error(f"❌ File {filename} not found. Please ensure the CSV file exists.")
        return []
    except Exception as e:
        logger.error(f"❌ Error reading CSV: {e}")
        return []

def get_archived_ticket_data(ticket_id):
    """Get archived ticket information including conversations"""
    url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/archived/{ticket_id}?include=conversations"
    
    try:
        response = rate_limited_request(url, auth=(API_KEY, 'X'))
        
        if response.status_code == 200:
            complete_data = response.json()
            # Mark as archived ticket
            complete_data["is_archived"] = True
            
            # Enhance ticket-level attachments with more details if they exist
            if complete_data.get("attachments"):
                enhanced_attachments = []
                for att in complete_data["attachments"]:
                    enhanced_attachments.append({
                        "id": att.get("id"),
                        "name": att.get("name"),
                        "url": att.get("attachment_url") or att.get("url"),
                        "content_type": att.get("content_type"),
                        "size": att.get("size"),
                        "created_at": att.get("created_at"),
                        "type": "ticket_attachment"  # Mark as ticket-level attachment
                    })
                complete_data["attachments"] = enhanced_attachments
            
            # Enhance conversation attachments if they exist
            if complete_data.get("conversations"):
                enhanced_conversations = []
                for convo in complete_data["conversations"]:
                    conversation_data = {
                        "id": convo.get("id"),
                        "body_text": convo.get("body_text"),
                        "body": convo.get("body"),
                        "private": convo.get("private"),
                        "created_at": convo.get("created_at"),
                        "updated_at": convo.get("updated_at"),
                        "user_id": convo.get("user_id"),
                        "incoming": convo.get("incoming"),
                        "source": convo.get("source"),
                        "support_email": convo.get("support_email"),
                        "to_emails": convo.get("to_emails"),
                        "from_email": convo.get("from_email"),
                        "cc_emails": convo.get("cc_emails"),
                        "bcc_emails": convo.get("bcc_emails"),
                        "email_headers": convo.get("email_headers"),
                        "ticket_id": convo.get("ticket_id"),
                        "conversation_type": convo.get("conversation_type"),
                        "channel": convo.get("channel")
                    }
                    
                    # Remove None values
                    conversation_data = {k: v for k, v in conversation_data.items() if v is not None}
                    
                    # Enhance conversation attachments
                    if convo.get("attachments"):
                        enhanced_conv_attachments = []
                        for att in convo.get("attachments", []):
                            enhanced_conv_attachments.append({
                                "id": att.get("id"),
                                "name": att.get("name"),
                                "url": att.get("attachment_url") or att.get("url"),
                                "content_type": att.get("content_type"),
                                "size": att.get("size"),
                                "created_at": convo.get("created_at"),
                                "updated_at": convo.get("updated_at"),
                                "user_id": convo.get("user_id"),
                                "conversation_id": convo.get("id"),
                                "type": "conversation_attachment"  # Mark as conversation attachment
                            })
                        conversation_data["attachments"] = enhanced_conv_attachments
                    
                    enhanced_conversations.append(conversation_data)
                
                complete_data["conversations"] = enhanced_conversations
            
            return complete_data
        else:
            logger.error(f"Error fetching archived ticket data for {ticket_id}: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching archived ticket {ticket_id}: {e}")
        return None

def get_complete_ticket_data(ticket_id):
    """Get complete ticket information including conversations with fallback strategy based on FRESH env var"""
    
    if FRESH == "y":
        # FRESH=y: Try active tickets first, then archived as fallback
        logger.info(f"🔄 FRESH=y: Trying active ticket {ticket_id} first...")
        
        # First try: Active ticket API
        url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}?include=conversations"
        try:
            response = rate_limited_request(url, auth=(API_KEY, 'X'))
            
            if response.status_code == 200:
                complete_data = response.json()
                complete_data["is_archived"] = False  # Mark as active ticket
                
                # Enhance ticket-level attachments with more details if they exist
                if complete_data.get("attachments"):
                    enhanced_attachments = []
                    for att in complete_data["attachments"]:
                        enhanced_attachments.append({
                            "id": att.get("id"),
                            "name": att.get("name"),
                            "url": att.get("attachment_url") or att.get("url"),
                            "content_type": att.get("content_type"),
                            "size": att.get("size"),
                            "created_at": att.get("created_at"),
                            "type": "ticket_attachment"  # Mark as ticket-level attachment
                        })
                    complete_data["attachments"] = enhanced_attachments
                
                # Enhance conversation attachments if they exist
                if complete_data.get("conversations"):
                    enhanced_conversations = []
                    for convo in complete_data["conversations"]:
                        conversation_data = {
                            "id": convo.get("id"),
                            "body_text": convo.get("body_text"),
                            "body": convo.get("body"),
                            "private": convo.get("private"),
                            "created_at": convo.get("created_at"),
                            "updated_at": convo.get("updated_at"),
                            "user_id": convo.get("user_id"),
                            "incoming": convo.get("incoming"),
                            "source": convo.get("source"),
                            "support_email": convo.get("support_email"),
                            "to_emails": convo.get("to_emails"),
                            "from_email": convo.get("from_email"),
                            "cc_emails": convo.get("cc_emails"),
                            "bcc_emails": convo.get("bcc_emails"),
                            "email_headers": convo.get("email_headers"),
                            "ticket_id": convo.get("ticket_id"),
                            "conversation_type": convo.get("conversation_type"),
                            "channel": convo.get("channel")
                        }
                        
                        # Remove None values
                        conversation_data = {k: v for k, v in conversation_data.items() if v is not None}
                        
                        # Enhance conversation attachments
                        if convo.get("attachments"):
                            enhanced_conv_attachments = []
                            for att in convo.get("attachments", []):
                                enhanced_conv_attachments.append({
                                    "id": att.get("id"),
                                    "name": att.get("name"),
                                    "url": att.get("attachment_url") or att.get("url"),
                                    "content_type": att.get("content_type"),
                                    "size": att.get("size"),
                                    "created_at": convo.get("created_at"),
                                    "updated_at": convo.get("updated_at"),
                                    "user_id": convo.get("user_id"),
                                    "conversation_id": convo.get("id"),
                                    "type": "conversation_attachment"  # Mark as conversation attachment
                                })
                            conversation_data["attachments"] = enhanced_conv_attachments
                        
                        enhanced_conversations.append(conversation_data)
                    
                    complete_data["conversations"] = enhanced_conversations
                
                logger.info(f"✅ Active ticket {ticket_id} found and processed")
                return complete_data
                
            elif response.status_code == 404:
                # Active ticket not found, try archived
                logger.info(f"⚠️ Active ticket {ticket_id} not found (404), trying archived...")
                archived_data = get_archived_ticket_data(ticket_id)
                if archived_data:
                    logger.info(f"✅ Archived ticket {ticket_id} found and processed")
                    return archived_data
                else:
                    logger.warning(f"❌ Neither active nor archived ticket {ticket_id} found")
                    return None
            else:
                logger.error(f"Error fetching active ticket {ticket_id}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching active ticket {ticket_id}: {e}")
            # Try archived as fallback
            logger.info(f"🔄 Trying archived ticket {ticket_id} as fallback...")
            return get_archived_ticket_data(ticket_id)
    
    elif FRESH == "n":
        # FRESH=n: Try archived tickets first, then active as fallback
        logger.info(f"🔄 FRESH=n: Trying archived ticket {ticket_id} first...")
        
        # First try: Archived ticket API
        archived_data = get_archived_ticket_data(ticket_id)
        if archived_data:
            logger.info(f"✅ Archived ticket {ticket_id} found and processed")
            return archived_data
        else:
            # Archived not found, try active as fallback
            logger.info(f"⚠️ Archived ticket {ticket_id} not found, trying active...")
            url = f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{ticket_id}?include=conversations"
            try:
                response = rate_limited_request(url, auth=(API_KEY, 'X'))
                
                if response.status_code == 200:
                    complete_data = response.json()
                    complete_data["is_archived"] = False  # Mark as active ticket
                    
                    # Enhance ticket-level attachments with more details if they exist
                    if complete_data.get("attachments"):
                        enhanced_attachments = []
                        for att in complete_data["attachments"]:
                            enhanced_attachments.append({
                                "id": att.get("id"),
                                "name": att.get("name"),
                                "url": att.get("attachment_url") or att.get("url"),
                                "content_type": att.get("content_type"),
                                "size": att.get("size"),
                                "created_at": att.get("created_at"),
                                "type": "ticket_attachment"  # Mark as ticket-level attachment
                            })
                        complete_data["attachments"] = enhanced_attachments
                    
                    # Enhance conversation attachments if they exist
                    if complete_data.get("conversations"):
                        enhanced_conversations = []
                        for convo in complete_data["conversations"]:
                            conversation_data = {
                                "id": convo.get("id"),
                                "body_text": convo.get("body_text"),
                                "body": convo.get("body"),
                                "private": convo.get("private"),
                                "created_at": convo.get("created_at"),
                                "updated_at": convo.get("updated_at"),
                                "user_id": convo.get("user_id"),
                                "incoming": convo.get("incoming"),
                                "source": convo.get("source"),
                                "support_email": convo.get("support_email"),
                                "to_emails": convo.get("to_emails"),
                                "from_email": convo.get("from_email"),
                                "cc_emails": convo.get("cc_emails"),
                                "bcc_emails": convo.get("bcc_emails"),
                                "email_headers": convo.get("email_headers"),
                                "ticket_id": convo.get("ticket_id"),
                                "conversation_type": convo.get("conversation_type"),
                                "channel": convo.get("channel")
                            }
                            
                            # Remove None values
                            conversation_data = {k: v for k, v in conversation_data.items() if v is not None}
                            
                            # Enhance conversation attachments
                            if convo.get("attachments"):
                                enhanced_conv_attachments = []
                                for att in convo.get("attachments", []):
                                    enhanced_conv_attachments.append({
                                        "id": att.get("id"),
                                        "name": att.get("name"),
                                        "url": att.get("attachment_url") or att.get("url"),
                                        "content_type": att.get("content_type"),
                                        "size": att.get("size"),
                                        "created_at": convo.get("created_at"),
                                        "updated_at": convo.get("updated_at"),
                                        "user_id": convo.get("user_id"),
                                        "conversation_id": convo.get("id"),
                                        "type": "conversation_attachment"  # Mark as conversation attachment
                            })
                                conversation_data["attachments"] = enhanced_conv_attachments
                            
                            enhanced_conversations.append(conversation_data)
                        
                        complete_data["conversations"] = enhanced_conversations
                    
                    logger.info(f"✅ Active ticket {ticket_id} found and processed as fallback")
                    return complete_data
                    
                elif response.status_code == 404:
                    logger.warning(f"❌ Neither archived nor active ticket {ticket_id} found")
                    return None
                else:
                    logger.error(f"Error fetching active ticket {ticket_id}: {response.status_code}")
                    return None
                    
            except Exception as e:
                logger.error(f"Error fetching active ticket {ticket_id}: {e}")
                return None
    else:
        logger.error(f"Invalid FRESH value: {FRESH}. Must be 'y' or 'n'")
        return None

def save_complete_ticket_data(ticket_id, complete_data, output_dir="complete_ticket_data"):
    """Save complete ticket data to a single JSON file"""
    try:
        # Create output directory if it doesn't exist
        Path(output_dir).mkdir(exist_ok=True)
        
        # Save complete data to single file
        filename = Path(output_dir) / f"ticket_{ticket_id}_complete.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ Saved complete data for ticket {ticket_id} to {filename}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error saving complete data for ticket {ticket_id}: {e}")
        return False

def extract_data_components(complete_data):
    """Extract different data components from the complete ticket data for analysis"""
    components = {
        "ticket_details": {},
        "conversations": [],
        "ticket_attachments": [],
        "conversation_attachments": []
    }
    
    if not complete_data:
        return components
    
    # Extract ticket details (everything except conversations)
    ticket_details = {k: v for k, v in complete_data.items() if k != "conversations"}
    components["ticket_details"] = ticket_details
    
    # Extract conversations
    conversations = complete_data.get("conversations", [])
    components["conversations"] = conversations
    
    # Extract ticket-level attachments
    ticket_attachments = complete_data.get("attachments", [])
    components["ticket_attachments"] = [att for att in ticket_attachments if att.get("type") == "ticket_attachment"]
    
    # Extract conversation attachments
    conversation_attachments = []
    for conv in conversations:
        if conv.get("attachments"):
            for att in conv["attachments"]:
                att["conversation_id"] = conv.get("id")
                att["ticket_id"] = complete_data.get("id")
                conversation_attachments.append(att)
    
    components["conversation_attachments"] = conversation_attachments
    
    return components

def process_ticket_batch(ticket_ids, batch_number):
    """Process a batch of tickets with consolidated single API call approach"""
    logger.info(f"\n--- Processing batch {batch_number} ({len(ticket_ids)} tickets) ---")
    
    batch_tickets = []
    batch_stats = {
        "successful": 0,
        "failed": 0,
        "total_attachments": 0,
        "total_conversations": 0,
        "total_conversation_attachments": 0
    }
    
    for i, ticket_id in enumerate(ticket_ids, 1):
        logger.info(f"Processing ticket {i}/{len(ticket_ids)} (ID: {ticket_id})")
        
        # Get complete ticket data with single API call
        complete_data = get_complete_ticket_data(ticket_id)
        
        if complete_data:
            # Save complete data to single JSON file
            if save_complete_ticket_data(ticket_id, complete_data):
                batch_tickets.append(complete_data)
                batch_stats["successful"] += 1
                
                # Update statistics
                conversations = complete_data.get("conversations", [])
                attachments = complete_data.get("attachments", [])
                
                batch_stats["total_conversations"] += len(conversations)
                batch_stats["total_attachments"] += len(attachments)
                
                # Count conversation attachments
                conv_attachments = 0
                for conv in conversations:
                    conv_attachments += len(conv.get("attachments", []))
                batch_stats["total_conversation_attachments"] += conv_attachments
                
                logger.info(f"✅ Extracted complete data for ticket {ticket_id} "
                          f"({len(conversations)} conversations, {len(attachments)} ticket attachments, "
                          f"{conv_attachments} conversation attachments)")
            else:
                batch_stats["failed"] += 1
                logger.error(f"❌ Failed to save data for ticket {ticket_id}")
        else:
            batch_stats["failed"] += 1
            logger.error(f"❌ Failed to extract data for ticket {ticket_id}")
        
        # Rate limiting between tickets
        if i < len(ticket_ids):
            logger.info(f"Waiting {CONFIG['delay_between_requests']} seconds...")
            time.sleep(CONFIG['delay_between_requests'])
    
    # Log batch statistics
    logger.info(f"\n📊 Batch {batch_number} Statistics:")
    logger.info(f"   ✅ Successful: {batch_stats['successful']}")
    logger.info(f"   ❌ Failed: {batch_stats['failed']}")
    logger.info(f"   💬 Total Conversations: {batch_stats['total_conversations']}")
    logger.info(f"   📎 Total Ticket Attachments: {batch_stats['total_attachments']}")
    logger.info(f"   📎 Total Conversation Attachments: {batch_stats['total_conversation_attachments']}")
    
    return batch_tickets

def main():
    """Main function to run consolidated ticket extraction"""
    print_usage_info()
    logger.info("🚀 Starting Consolidated Ticket Data Extraction")
    logger.info(f"Configuration: {CONFIG}")
    
    # Check for existing progress
    progress = load_progress()
    if progress and CONFIG.get('resume_enabled', True):
        logger.info(f"Found existing progress: {progress['total_processed']} tickets processed")
        resume_choice = input("Do you want to resume from where you left off? (y/n): ").lower()
        if resume_choice == 'y':
            processed_tickets = progress['processed_tickets']
            start_batch = progress['batch_number']
        else:
            processed_tickets = []
            start_batch = 1
    else:
        processed_tickets = []
        start_batch = 1
    
    # Read ticket IDs from CSV
    ticket_ids = read_ticket_ids_from_csv()
    
    if not ticket_ids:
        logger.error("❌ No ticket IDs found. Please run step1_get_ticket_ids.py first.")
        return
    
    # Skip already processed tickets
    if processed_tickets:
        ticket_ids = [tid for tid in ticket_ids if tid not in processed_tickets]
        logger.info(f"Skipping {len(processed_tickets)} already processed tickets")
    
    total_tickets = len(ticket_ids)
    total_batches = (total_tickets + CONFIG['batch_size'] - 1) // CONFIG['batch_size']
    
    logger.info(f"Processing {total_tickets} tickets in {total_batches} batches")
    
    # Process tickets in batches
    for batch_num in range(start_batch, total_batches + 1):
        start_idx = (batch_num - 1) * CONFIG['batch_size']
        end_idx = min(start_idx + CONFIG['batch_size'], total_tickets)
        batch_ticket_ids = ticket_ids[start_idx:end_idx]
        
        logger.info(f"\n{'='*50}")
        logger.info(f"BATCH {batch_num}/{total_batches}")
        logger.info(f"Processing tickets {start_idx+1}-{end_idx} of {total_tickets}")
        logger.info(f"{'='*50}")
        
        # Process batch
        batch_tickets = process_ticket_batch(batch_ticket_ids, batch_num)
        
        if batch_tickets:
            # Individual ticket files are already saved by process_ticket_batch
            # Update progress
            processed_tickets.extend(batch_ticket_ids)
            save_progress(processed_tickets, batch_num)
            
            logger.info(f"✅ Batch {batch_num} completed: {len(batch_tickets)} tickets")
        else:
            logger.error(f"❌ Batch {batch_num} failed")
        
        # Rate limiting between batches
        if batch_num < total_batches:
            logger.info(f"Waiting {CONFIG['delay_between_batches']} seconds before next batch...")
            time.sleep(CONFIG['delay_between_batches'])
    
    # Generate final summary
    generate_extraction_summary(processed_tickets)
    
    logger.info(f"\n🎉 Step 2 completed! Processed {len(processed_tickets)} tickets")
    logger.info("📁 Complete ticket data saved in 'complete_ticket_data/' directory")
    logger.info("📊 Each ticket has a single JSON file with all data (ticket details, conversations, attachments)")
    
    # Clean up progress file on successful completion
    if os.path.exists("step2_progress.json"):
        os.remove("step2_progress.json")
        logger.info("Cleaned up progress file")
    
    # Clean up connections
    cleanup_connections()

def generate_extraction_summary(processed_tickets):
    """Generate a summary of the extraction process"""
    summary = {
        "extraction_timestamp": datetime.now().isoformat(),
        "total_tickets_processed": len(processed_tickets),
        "processed_ticket_ids": processed_tickets,
        "api_approach": "single_consolidated_call",
        "api_endpoint": f"https://{FRESHDESK_DOMAIN}/api/v2/tickets/{{ticket_id}}?include=conversations",
        "output_format": "single_json_per_ticket",
        "output_directory": "complete_ticket_data",
        "data_included": [
            "ticket_details",
            "conversations",
            "ticket_attachments", 
            "conversation_attachments"
        ]
    }
    
    # Count statistics from saved files
    output_dir = Path("complete_ticket_data")
    if output_dir.exists():
        total_conversations = 0
        total_ticket_attachments = 0
        total_conversation_attachments = 0
        
        for ticket_id in processed_tickets:
            ticket_file = output_dir / f"ticket_{ticket_id}_complete.json"
            if ticket_file.exists():
                try:
                    with open(ticket_file, 'r', encoding='utf-8') as f:
                        ticket_data = json.load(f)
                    
                    conversations = ticket_data.get("conversations", [])
                    attachments = ticket_data.get("attachments", [])
                    
                    total_conversations += len(conversations)
                    total_ticket_attachments += len(attachments)
                    
                    for conv in conversations:
                        total_conversation_attachments += len(conv.get("attachments", []))
                        
                except Exception as e:
                    logger.warning(f"Could not read ticket file for summary: {ticket_file}")
        
        summary["statistics"] = {
            "total_conversations": total_conversations,
            "total_ticket_attachments": total_ticket_attachments,
            "total_conversation_attachments": total_conversation_attachments,
            "average_conversations_per_ticket": round(total_conversations / len(processed_tickets), 2) if processed_tickets else 0
        }
    
    # Save summary
    summary_file = "extraction_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    logger.info(f"📊 Extraction summary saved to {summary_file}")
    
    # Log key statistics
    if summary.get("statistics"):
        stats = summary["statistics"]
        logger.info(f"📈 Final Statistics:")
        logger.info(f"   🎫 Total Tickets: {summary['total_tickets_processed']}")
        logger.info(f"   💬 Total Conversations: {stats['total_conversations']}")
        logger.info(f"   📎 Total Ticket Attachments: {stats['total_ticket_attachments']}")
        logger.info(f"   📎 Total Conversation Attachments: {stats['total_conversation_attachments']}")
        logger.info(f"   📊 Avg Conversations/Ticket: {stats['average_conversations_per_ticket']}")

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_connections() 