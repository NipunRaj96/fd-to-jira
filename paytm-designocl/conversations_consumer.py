#!/usr/bin/env python3
"""
Conversations Consumer

Runs independently with N workers. Continuously claims records where
`Conversation Attachments` is null in `migration/ticket_details.json`, marks them
as in-progress ("I"), downloads conversation-level attachments from
`conversation_attachments/ticket_{id}_conversation_attachments.json`, and finally updates the
status to either a mapping {id: timestamp_when_download_completed} or "NA" if none.

It also provides a finalize pass to resolve lingering "I" into mapping/NA.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

from download_attachments import download_file, sanitize_filename
from migration_store import (
    claim_next_null_conversation_attachments,
    set_conversation_attachments_status,
    finalize_in_progress_conversations,
)
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(InsecureRequestWarning)


OUTPUT_DIRS = {
    'conversation_attachments': Path('conversation_attachments'),
}


CONFIG = {
    'workers': 10,
    'max_wait_for_json_seconds': 30,
    'max_retries': 3,
    'retry_delay': 2,
    'freshdesk_domain': 'paytm-designocl.freshdesk.com',
    'api_key': 'TSBbicEhvmC9IBtQ:X',
}


def evaluate_status(ticket_id: int) -> Any:
    conv_att_file = OUTPUT_DIRS['conversation_attachments'] / f"ticket_{ticket_id}_conversation_attachments.json"
    if conv_att_file.exists():
        try:
            data = json.loads(conv_att_file.read_text(encoding='utf-8') or '[]')
            if isinstance(data, list) and len(data) > 0:
                now_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                return {str(att.get('id')): now_iso for att in data if att.get('id')}
        except Exception:
            pass
    return "NA"


def fetch_fresh_metadata(ticket_id: int) -> List[Dict[str, Any]]:
    """Fetch fresh metadata for a ticket when URLs expire"""
    try:
        session = requests.Session()
        session.auth = (CONFIG['api_key'], 'X')
        session.verify = False
        session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Freshdesk-Migration/1.0'
        })
        
        url = f"https://{CONFIG['freshdesk_domain']}/api/v2/tickets/{ticket_id}/conversations"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        conversations = response.json()
        attachments = []
        
        for conv in conversations:
            if 'attachments' in conv and conv['attachments']:
                for att in conv['attachments']:
                    attachments.append({
                        'id': att.get('id'),
                        'name': att.get('name'),
                        'url': att.get('url') or att.get('attachment_url'),
                        'content_type': att.get('content_type'),
                        'size': att.get('size'),
                        'conversation_id': conv.get('id'),
                        'ticket_id': ticket_id
                    })
        
        logging.info(f"[conversation_attachments] Refreshed metadata for ticket {ticket_id}: {len(attachments)} attachments")
        return attachments
        
    except Exception as e:
        logging.error(f"[conversation_attachments] Failed to refresh metadata for ticket {ticket_id}: {e}")
        return []


def process_one(ticket_id: int) -> None:
    logging.info(f"[conversation_attachments] Claimed ticket {ticket_id} -> I")
    conv_att_file = OUTPUT_DIRS['conversation_attachments'] / f"ticket_{ticket_id}_conversation_attachments.json"

    waited = 0.0
    while not conv_att_file.exists() and waited < CONFIG['max_wait_for_json_seconds']:
        time.sleep(0.5)
        waited += 0.5
    if not conv_att_file.exists():
        set_conversation_attachments_status(ticket_id, "NA")
        logging.info(f"[conversation_attachments] Finalized ticket {ticket_id} -> NA (no JSON after {waited}s)")
        return

    try:
        raw_list = json.loads(conv_att_file.read_text(encoding='utf-8') or '[]')
    except Exception:
        set_conversation_attachments_status(ticket_id, "NA")
        logging.info(f"[conversation_attachments] Finalized ticket {ticket_id} -> NA (malformed JSON)")
        return

    if not isinstance(raw_list, list) or len(raw_list) == 0:
        set_conversation_attachments_status(ticket_id, "NA")
        logging.info(f"[conversation_attachments] Finalized ticket {ticket_id} -> NA (no conversation attachments)")
        return

    ticket_dir = Path('conversation_attachments_downloads') / str(ticket_id)
    ticket_dir.mkdir(parents=True, exist_ok=True)

    def attempt_downloads(attachments_list: List[Dict[str, Any]]) -> Dict[str, str]:
        mapping_local: Dict[str, str] = {}
        urls_expired = False
        
        for att in attachments_list:
            att_id = att.get('id')
            name = att.get('name')
            url = att.get('url') or att.get('attachment_url')
            if not (att_id and name and url):
                continue
                
            safe_name = sanitize_filename(str(name))
            dest = ticket_dir / safe_name
            
            if dest.exists():
                mapping_local[str(att_id)] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                continue
            
            # Try to download with retries
            download_success = False
            for attempt in range(CONFIG['max_retries']):
                try:
                    ok = download_file(url, str(dest))
                    if ok:
                        mapping_local[str(att_id)] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                        download_success = True
                        break
                    else:
                        logging.warning(f"[conversation_attachments] Download attempt {attempt + 1} failed for {name}")
                        if attempt < CONFIG['max_retries'] - 1:
                            time.sleep(CONFIG['retry_delay'])
                except Exception as e:
                    if "403" in str(e) or "Forbidden" in str(e) or "expired" in str(e).lower():
                        urls_expired = True
                        logging.warning(f"[conversation_attachments] URLs expired for ticket {ticket_id}, will refresh metadata")
                        break
                    else:
                        logging.warning(f"[conversation_attachments] Download error for {name}: {e}")
                        if attempt < CONFIG['max_retries'] - 1:
                            time.sleep(CONFIG['retry_delay'])
            
            if not download_success and not urls_expired:
                logging.error(f"[conversation_attachments] Failed to download {name} after {CONFIG['max_retries']} attempts")
        
        return mapping_local, urls_expired

    try:
        # First attempt with existing metadata
        mapping, urls_expired = attempt_downloads(raw_list)
        
        # If URLs expired, try with fresh metadata
        if urls_expired:
            logging.info(f"[conversation_attachments] URLs expired for ticket {ticket_id}, fetching fresh metadata...")
            fresh_attachments = fetch_fresh_metadata(ticket_id)
            
            if fresh_attachments:
                # Update the JSON file with fresh metadata
                output_file = OUTPUT_DIRS['conversation_attachments'] / f"ticket_{ticket_id}_conversation_attachments.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(fresh_attachments, f, indent=2, ensure_ascii=False)
                
                # Try downloads again with fresh metadata
                mapping, _ = attempt_downloads(fresh_attachments)
                logging.info(f"[conversation_attachments] Retried with fresh metadata for ticket {ticket_id}")
            else:
                logging.error(f"[conversation_attachments] Failed to fetch fresh metadata for ticket {ticket_id}")
        
        if mapping:
            set_conversation_attachments_status(ticket_id, mapping)
            logging.info(f"[conversation_attachments] Finalized ticket {ticket_id} -> mapping({len(mapping)})")
        else:
            set_conversation_attachments_status(ticket_id, "NA")
            logging.info(f"[conversation_attachments] Finalized ticket {ticket_id} -> NA (downloads failed)")
    except Exception as e:
        logging.error(f"[conversation_attachments] Error processing ticket {ticket_id}: {e}")
        set_conversation_attachments_status(ticket_id, "NA")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('conversations_consumer.log', mode='a', encoding='utf-8')
        ],
        force=True,
    )

    logging.info('Conversations Consumer starting...')
    
    # Create output directory
    Path('conversation_attachments_downloads').mkdir(exist_ok=True)

    with ThreadPoolExecutor(max_workers=CONFIG['workers']) as exe:
        while True:
            ticket_id = claim_next_null_conversation_attachments()
            if ticket_id == -1:
                logging.info('No more tickets to process. Waiting...')
                time.sleep(5)
                continue
            
            exe.submit(process_one, ticket_id)

    return 0


if __name__ == '__main__':
    raise SystemExit(main()) 