#!/usr/bin/env python3
"""
Reprocess Mismatched Ticket Attachments

This script identifies tickets with mismatched ticket attachments and
reprocesses only those specific tickets to achieve 100% accuracy.
Includes URL refresh for expired Freshdesk URLs.
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from extract_ticket_details import get_complete_ticket_data
from download_attachments import download_file, sanitize_filename
from migration_store import (
    set_attachments_status,
    set_conversations_status
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('reprocess_mismatched_ticket_attachments.log', mode='a', encoding='utf-8')
    ],
    force=True,
)

logger = logging.getLogger(__name__)

OUTPUT_DIRS = {
    'ticket_attachments': Path('ticket_attachments'),
    'conversations': Path('conversations'),
    'conversation_attachments': Path('conversation_attachments'),
    'attachments': Path('attachments'),
}

CONFIG = {
    'workers': 5,  # Reduced workers for targeted reprocessing with URL refresh
    'max_retries': 3,
    'delay_between_requests': 0.2,  # Reduced delay for faster processing
    'url_refresh_timeout': 300,  # 5 minutes in seconds
}


def count_metadata_urls(file_path: Path) -> int:
    """Count URLs in metadata file"""
    try:
        data = json.loads(file_path.read_text(encoding='utf-8') or '[]')
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            return 1 if data else 0
        return 0
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return 0


def count_downloaded_files(ticket_id: int, is_conversation: bool = False) -> int:
    """Count downloaded files in attachments folder"""
    attachments_dir = OUTPUT_DIRS['attachments'] / str(ticket_id)
    if not attachments_dir.exists():
        return 0
    
    if is_conversation:
        # Count conversation attachment files
        conv_files = list(attachments_dir.glob('conv_*'))
        return len(conv_files)
    else:
        # Count ticket attachment files
        ticket_files = list(attachments_dir.glob('*'))
        conv_files = list(attachments_dir.glob('conv_*'))
        return len(ticket_files) - len(conv_files)


def identify_mismatched_ticket_attachments() -> List[Dict[str, Any]]:
    """Identify tickets with mismatched ticket attachments"""
    logger.info("🔍 Identifying mismatched ticket attachments...")
    
    ticket_attachments_dir = OUTPUT_DIRS['ticket_attachments']
    if not ticket_attachments_dir.exists():
        logger.error("❌ ticket_attachments folder not found")
        return []
    
    mismatched_tickets = []
    
    for file_path in ticket_attachments_dir.glob('ticket_*_attachments.json'):
        ticket_id = int(file_path.stem.split('_')[1])
        
        metadata_count = count_metadata_urls(file_path)
        downloaded_count = count_downloaded_files(ticket_id, is_conversation=False)
        
        if metadata_count != downloaded_count:
            mismatched_tickets.append({
                'ticket_id': ticket_id,
                'metadata_urls': metadata_count,
                'downloaded': downloaded_count,
                'missing_count': metadata_count - downloaded_count
            })
    
    logger.info(f"📊 Found {len(mismatched_tickets)} tickets with mismatched ticket attachments")
    return mismatched_tickets


def reset_ticket_status(ticket_id: int) -> None:
    """Reset the ticket status in migration store to allow reprocessing"""
    try:
        # Reset ticket attachments status
        set_attachments_status(ticket_id, None)
        logger.info(f"[{ticket_id}] Reset ticket attachments status")
        
        # Reset conversations status if needed
        set_conversations_status(ticket_id, None)
        logger.info(f"[{ticket_id}] Reset conversations status")
            
    except Exception as e:
        logger.error(f"[{ticket_id}] Error resetting status: {e}")


def refresh_ticket_attachments(ticket_id: int) -> List[Dict[str, Any]]:
    """Refresh ticket attachments by re-fetching from Freshdesk API"""
    logger.info(f"[{ticket_id}] Refreshing ticket attachments from Freshdesk...")
    
    try:
        # Use get_complete_ticket_data to get fresh ticket data
        complete_data = get_complete_ticket_data(ticket_id)
        if not complete_data:
            logger.warning(f"[{ticket_id}] Could not fetch ticket data from API")
            return []
        
        # Extract ticket-level attachments (not conversation attachments)
        all_attachments = complete_data.get('attachments', [])
        ticket_attachments = [att for att in all_attachments if att.get('type') == 'ticket_attachment']
        
        if not ticket_attachments:
            logger.warning(f"[{ticket_id}] No ticket attachments found in fresh API response")
            return []
        
        # Update the ticket attachments JSON file
        ticket_att_file = OUTPUT_DIRS['ticket_attachments'] / f"ticket_{ticket_id}_attachments.json"
        ticket_att_file.write_text(json.dumps(ticket_attachments, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"[{ticket_id}] Refreshed {len(ticket_attachments)} ticket attachments")
        
        return ticket_attachments
        
    except Exception as e:
        logger.error(f"[{ticket_id}] Error refreshing ticket attachments: {e}")
        return []


def reprocess_ticket_attachments(ticket_id: int) -> bool:
    """Reprocess ticket attachments for a specific ticket with URL refresh"""
    logger.info(f"[{ticket_id}] Starting reprocessing...")
    
    try:
        # First, refresh URLs from Freshdesk API
        refreshed_attachments = refresh_ticket_attachments(ticket_id)
        
        # Get ticket attachments metadata (use refreshed if available)
        ticket_att_file = OUTPUT_DIRS['ticket_attachments'] / f"ticket_{ticket_id}_attachments.json"
        if not ticket_att_file.exists():
            logger.warning(f"[{ticket_id}] No ticket attachments metadata found")
            set_attachments_status(ticket_id, "NA")
            return True
        
        # Load attachment metadata
        raw_list = json.loads(ticket_att_file.read_text(encoding='utf-8') or '[]')
        if not isinstance(raw_list, list) or len(raw_list) == 0:
            logger.info(f"[{ticket_id}] No ticket attachments to process")
            set_attachments_status(ticket_id, "NA")
            return True
        
        # Create ticket directory
        ticket_dir = OUTPUT_DIRS['attachments'] / str(ticket_id)
        ticket_dir.mkdir(parents=True, exist_ok=True)
        
        # Track filenames to handle duplicates
        used_filenames = set()
        
        # Download missing attachments
        successful_downloads = 0
        mapping: Dict[str, str] = {}
        
        for att in raw_list:
            att_id = att.get('id')
            name = att.get('name')
            url = att.get('url') or att.get('attachment_url')
            
            if not (att_id and name and url):
                continue
            
            # Create unique filename to handle duplicates
            safe_name = sanitize_filename(str(name))
            base_name = safe_name
            counter = 1
            
            # If filename already exists, append counter
            while safe_name in used_filenames:
                name_parts = base_name.rsplit('.', 1)
                if len(name_parts) > 1:
                    safe_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                else:
                    safe_name = f"{base_name}_{counter}"
                counter += 1
            
            used_filenames.add(safe_name)
            dest = ticket_dir / safe_name
            
            if dest.exists():
                mapping[str(att_id)] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                successful_downloads += 1
                continue
            
            # Attempt download with retries and URL refresh
            download_success = False
            current_url = url
            metadata_refreshed = False
            
            for attempt in range(CONFIG['max_retries']):
                try:
                    if download_file(current_url, str(dest)):
                        mapping[str(att_id)] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                        successful_downloads += 1
                        download_success = True
                        logger.info(f"[{ticket_id}] Downloaded ticket_attachment {att_id}: {safe_name}")
                        break
                    else:
                        logger.warning(f"[{ticket_id}] Download attempt {attempt + 1} failed for {att_id}")
                        if attempt < CONFIG['max_retries'] - 1:
                            # If first attempt failed, try refreshing URL
                            if attempt == 0:
                                logger.info(f"[{ticket_id}] Refreshing URL for attachment {att_id}")
                                refreshed = refresh_ticket_attachments(ticket_id)
                                if refreshed:
                                    # Find the refreshed attachment
                                    for ref_att in refreshed:
                                        if ref_att.get('id') == att_id:
                                            new_url = ref_att.get('url') or ref_att.get('attachment_url')
                                            if new_url and new_url != current_url:
                                                current_url = new_url
                                                metadata_refreshed = True
                                                logger.info(f"[{ticket_id}] Got fresh URL for {att_id}")
                                                break
                                    if not metadata_refreshed:
                                        logger.warning(f"[{ticket_id}] Could not refresh URL for {att_id}")
                                else:
                                    logger.warning(f"[{ticket_id}] Failed to refresh metadata for {att_id}")
                            
                            wait_time = 1  # Wait before retry
                            time.sleep(wait_time)
                except Exception as e:
                    error_msg = str(e)
                    if "403" in error_msg or "Forbidden" in error_msg:
                        logger.warning(f"[{ticket_id}] URL expired (403 Forbidden) for {att_id}")
                        if not metadata_refreshed:
                            logger.info(f"[{ticket_id}] Fetching fresh metadata due to expired URL...")
                            refreshed = refresh_ticket_attachments(ticket_id)
                            if refreshed:
                                # Find the refreshed attachment
                                for ref_att in refreshed:
                                    if ref_att.get('id') == att_id:
                                        new_url = ref_att.get('url') or ref_att.get('attachment_url')
                                        if new_url and new_url != current_url:
                                            current_url = new_url
                                            metadata_refreshed = True
                                            logger.info(f"[{ticket_id}] Got fresh URL after 403 error: {att_id}")
                                            break
                    else:
                        logger.error(f"[{ticket_id}] Error downloading {att_id}: {e}")
                    
                    if attempt < CONFIG['max_retries'] - 1:
                        wait_time = 1
                        time.sleep(wait_time)
            
            # Add delay between requests
            time.sleep(CONFIG['delay_between_requests'])
        
        # Update status
        if mapping:
            set_attachments_status(ticket_id, mapping)
            logger.info(f"[{ticket_id}] Successfully processed {successful_downloads}/{len(raw_list)} attachments")
        else:
            set_attachments_status(ticket_id, "NA")
            logger.info(f"[{ticket_id}] No attachments successfully processed")
        
        return True
        
    except Exception as e:
        logger.error(f"[{ticket_id}] Error during reprocessing: {e}")
        return False


def main() -> int:
    """Main reprocessing function"""
    logger.info("🚀 STARTING MISMATCHED TICKET ATTACHMENTS REPROCESSING")
    logger.info("=" * 70)
    logger.info("⚠️  IMPORTANT: Freshdesk URLs expire in ~5 minutes!")
    logger.info("   This script refreshes URLs and downloads quickly.")
    
    # Ensure output directories exist
    for dir_path in OUTPUT_DIRS.values():
        dir_path.mkdir(exist_ok=True)
    
    # Identify mismatched tickets
    mismatched_tickets = identify_mismatched_ticket_attachments()
    if not mismatched_tickets:
        logger.info("✅ No mismatched tickets found. All ticket attachments are already downloaded!")
        return 0
    
    # Sort by missing count (most missing first)
    mismatched_tickets.sort(key=lambda x: x['missing_count'], reverse=True)
    
    logger.info(f"📋 REPROCESSING {len(mismatched_tickets)} TICKETS:")
    for ticket in mismatched_tickets[:10]:  # Show first 10
        logger.info(f"   Ticket {ticket['ticket_id']}: {ticket['missing_count']} missing out of {ticket['metadata_urls']}")
    if len(mismatched_tickets) > 10:
        logger.info(f"   ... and {len(mismatched_tickets) - 10} more")
    
    # Reset status for all mismatched tickets
    logger.info("🔄 Resetting ticket statuses...")
    for ticket in mismatched_tickets:
        reset_ticket_status(ticket['ticket_id'])
    
    # Reprocess tickets with multithreading
    logger.info("🚀 Starting reprocessing with multithreading...")
    logger.info(f"   Using {CONFIG['workers']} workers for optimal speed")
    successful = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=CONFIG['workers']) as executor:
        # Submit ticket attachments reprocessing
        future_to_ticket = {
            executor.submit(reprocess_ticket_attachments, ticket['ticket_id']): ticket['ticket_id']
            for ticket in mismatched_tickets
        }
        
        # Process results
        for future in as_completed(future_to_ticket):
            ticket_id = future_to_ticket[future]
            try:
                if future.result():
                    successful += 1
                    logger.info(f"✅ [{ticket_id}] Reprocessing completed successfully")
                else:
                    failed += 1
                    logger.error(f"❌ [{ticket_id}] Reprocessing failed")
            except Exception as e:
                failed += 1
                logger.error(f"❌ [{ticket_id}] Exception during reprocessing: {e}")
    
    # Final verification
    logger.info("🔍 Final verification...")
    final_mismatched = identify_mismatched_ticket_attachments()
    
    logger.info("=" * 70)
    logger.info("🎯 REPROCESSING SUMMARY:")
    logger.info(f"   Total tickets processed: {len(mismatched_tickets)}")
    logger.info(f"   Successful: {successful}")
    logger.info(f"   Failed: {failed}")
    logger.info(f"   Remaining mismatched: {len(final_mismatched)}")
    
    if final_mismatched:
        logger.warning(f"⚠️  {len(final_mismatched)} tickets still have mismatched attachments")
        logger.warning("Consider running this script again or investigating manually")
        logger.info("💡 Tip: Run with fewer workers if you encounter rate limiting")
    else:
        logger.info("🎉 SUCCESS! All ticket attachments are now downloaded!")
    
    return 0 if not final_mismatched else 1


if __name__ == '__main__':
    raise SystemExit(main()) 