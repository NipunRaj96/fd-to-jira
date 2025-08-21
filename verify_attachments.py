#!/usr/bin/env python3
"""
Verify Attachment Downloads

This script checks if all attachments mentioned in metadata files
are actually downloaded in the attachments folder.
"""

import json
import os
from pathlib import Path

def count_metadata_urls(file_path):
    """Count URLs in metadata file"""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            # Handle single attachment case
            return 1 if data else 0
        return 0
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0

def count_downloaded_files(ticket_id, is_conversation=False):
    """Count downloaded files in attachments folder"""
    attachments_dir = Path('attachments') / str(ticket_id)
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

def verify_ticket_attachments():
    """Verify ticket attachments"""
    print("🔍 VERIFYING TICKET ATTACHMENTS...")
    print("=" * 60)
    
    ticket_attachments_dir = Path('ticket_attachments')
    if not ticket_attachments_dir.exists():
        print("❌ ticket_attachments folder not found")
        return
    
    total_tickets = 0
    total_metadata_urls = 0
    total_downloaded = 0
    mismatched_tickets = []
    
    for file_path in ticket_attachments_dir.glob('ticket_*_attachments.json'):
        ticket_id = file_path.stem.split('_')[1]
        total_tickets += 1
        
        metadata_count = count_metadata_urls(file_path)
        downloaded_count = count_downloaded_files(ticket_id, is_conversation=False)
        total_metadata_urls += metadata_count
        total_downloaded += downloaded_count
        
        if metadata_count != downloaded_count:
            mismatched_tickets.append({
                'ticket_id': ticket_id,
                'metadata_urls': metadata_count,
                'downloaded': downloaded_count
            })
    
    print(f"📊 TICKET ATTACHMENTS SUMMARY:")
    print(f"   Total tickets with metadata: {total_tickets}")
    print(f"   Total metadata URLs: {total_metadata_urls}")
    print(f"   Total downloaded files: {total_downloaded}")
    print(f"   Success rate: {(total_downloaded/total_metadata_urls*100):.1f}%" if total_metadata_urls > 0 else "   Success rate: N/A")
    
    if mismatched_tickets:
        print(f"\n⚠️  MISMATCHED TICKETS ({len(mismatched_tickets)}):")
        for ticket in mismatched_tickets[:10]:  # Show first 10
            print(f"   Ticket {ticket['ticket_id']}: {ticket['metadata_urls']} URLs, {ticket['downloaded']} downloaded")
        if len(mismatched_tickets) > 10:
            print(f"   ... and {len(mismatched_tickets) - 10} more")
    else:
        print("\n✅ ALL TICKET ATTACHMENTS MATCH!")
    
    return total_tickets, total_metadata_urls, total_downloaded

def verify_conversation_attachments():
    """Verify conversation attachments"""
    print("\n🔍 VERIFYING CONVERSATION ATTACHMENTS...")
    print("=" * 60)
    
    conv_attachments_dir = Path('conversation_attachments')
    if not conv_attachments_dir.exists():
        print("❌ conversation_attachments folder not found")
        return
    
    total_tickets = 0
    total_metadata_urls = 0
    total_downloaded = 0
    mismatched_tickets = []
    
    for file_path in conv_attachments_dir.glob('ticket_*_conversation_attachments.json'):
        ticket_id = file_path.stem.split('_')[1]
        total_tickets += 1
        
        metadata_count = count_metadata_urls(file_path)
        downloaded_count = count_downloaded_files(ticket_id, is_conversation=True)
        total_metadata_urls += metadata_count
        total_downloaded += downloaded_count
        
        if metadata_count != downloaded_count:
            mismatched_tickets.append({
                'ticket_id': ticket_id,
                'metadata_urls': metadata_count,
                'downloaded': downloaded_count
            })
    
    print(f"📊 CONVERSATION ATTACHMENTS SUMMARY:")
    print(f"   Total tickets with metadata: {total_tickets}")
    print(f"   Total metadata URLs: {total_metadata_urls}")
    print(f"   Total downloaded files: {total_downloaded}")
    print(f"   Success rate: {(total_downloaded/total_metadata_urls*100):.1f}%" if total_metadata_urls > 0 else "   Success rate: N/A")
    
    if mismatched_tickets:
        print(f"\n⚠️  MISMATCHED TICKETS ({len(mismatched_tickets)}):")
        for ticket in mismatched_tickets[:10]:  # Show first 10
            print(f"   Ticket {ticket['ticket_id']}: {ticket['metadata_urls']} URLs, {ticket['downloaded']} downloaded")
        if len(mismatched_tickets) > 10:
            print(f"   ... and {len(mismatched_tickets) - 10} more")
    else:
        print("\n✅ ALL CONVERSATION ATTACHMENTS MATCH!")
    
    return total_tickets, total_metadata_urls, total_downloaded

def main():
    """Main verification function"""
    print("🚀 ATTACHMENT DOWNLOAD VERIFICATION")
    print("=" * 60)
    
    # Verify ticket attachments
    ticket_stats = verify_ticket_attachments()
    
    # Verify conversation attachments
    conv_stats = verify_conversation_attachments()
    
    # Overall summary
    if ticket_stats and conv_stats:
        total_metadata = ticket_stats[1] + conv_stats[1]
        total_downloaded = ticket_stats[2] + conv_stats[2]
        
        print("\n" + "=" * 60)
        print("🎯 OVERALL SUMMARY:")
        print(f"   Total metadata URLs: {total_metadata}")
        print(f"   Total downloaded files: {total_downloaded}")
        print(f"   Overall success rate: {(total_downloaded/total_metadata*100):.1f}%" if total_metadata > 0 else "   Overall success rate: N/A")
        
        if total_downloaded == total_metadata:
            print("🎉 PERFECT! ALL ATTACHMENTS DOWNLOADED!")
        else:
            print(f"⚠️  {total_metadata - total_downloaded} attachments still need to be downloaded")

if __name__ == '__main__':
    main() 