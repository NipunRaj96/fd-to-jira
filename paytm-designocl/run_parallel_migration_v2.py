#!/usr/bin/env python3
"""
Parallel Migration Runner V2

Runs details_producer.py and download_attachments.py in parallel to avoid
metadata expiration issues. Freshdesk attachment URLs expire after just 5 minutes,
so we need to download everything quickly after metadata collection.

Phases:
1. details_producer.py - Extract ticket data and metadata
2. download_attachments.py - Download all attachments (ticket + conversation)

Both phases run simultaneously to maximize speed and minimize expiration.
"""

import subprocess
import time
import logging
import signal
import sys
from pathlib import Path
from typing import List, Optional


def setup_logging():
    """Setup logging for the parallel migration runner"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(threadName)s] %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('parallel_migration_v2.log', mode='a', encoding='utf-8')
        ],
        force=True,
    )


def start_phase(script_name: str, description: str) -> Optional[subprocess.Popen]:
    """Start a migration phase as a subprocess"""
    try:
        logging.info(f"Starting {description} ({script_name})...")
        process = subprocess.Popen(
            [sys.executable, script_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        logging.info(f"✅ {description} started with PID {process.pid}")
        return process
    except Exception as e:
        logging.error(f"❌ Failed to start {description}: {e}")
        return None


def monitor_process(process: subprocess.Popen, description: str) -> bool:
    """Monitor a process and return True if it's still running"""
    if process.poll() is None:
        return True  # Still running

    # Process has finished
    stdout, stderr = process.communicate()
    if process.returncode == 0:
        logging.info(f"✅ {description} completed successfully")
    else:
        logging.error(f"❌ {description} failed with return code {process.returncode}")
        if stderr:
            logging.error(f"Error output: {stderr}")

    return False


def wait_for_metadata_files():
    """Wait for metadata files to be generated before starting download_attachments.py"""
    logging.info("⏳ Waiting for metadata files to be generated...")
    
    # Wait for at least some ticket details and conversation files
    while True:
        ticket_details_count = len(list(Path('ticket_details').glob('*.json')))
        conversation_count = len(list(Path('conversation_attachments').glob('*.json')))
        
        if ticket_details_count >= 5 and conversation_count >= 5:
            logging.info(f"✅ Metadata files ready: {ticket_details_count} ticket details, {conversation_count} conversation attachments")
            break
        
        logging.info(f"⏳ Waiting... Found {ticket_details_count} ticket details, {conversation_count} conversation attachments")
        time.sleep(10)


def main():
    """Main parallel migration runner"""
    setup_logging()
    logging.info("🚀 Starting Parallel Migration Runner V2")
    logging.info("📋 Using download_attachments.py instead of separate consumers")

    # Check if required scripts exist
    required_scripts = [
        'details_producer.py',
        'download_attachments.py'
    ]

    for script in required_scripts:
        if not Path(script).exists():
            logging.error(f"❌ Required script {script} not found!")
            return 1

    # Start Phase 1: Details Producer
    details_proc = start_phase('details_producer.py', 'Phase 1: Details Producer')
    if not details_proc:
        logging.error("❌ Failed to start details producer!")
        return 1

    # Wait for metadata files to be generated
    wait_for_metadata_files()

    # Start Phase 2: Download Attachments (runs in parallel)
    attachments_proc = start_phase('download_attachments.py', 'Phase 2: Download Attachments')
    if not attachments_proc:
        logging.error("❌ Failed to start download attachments!")
        details_proc.terminate()
        return 1

    processes = {
        'details_producer': details_proc,
        'download_attachments': attachments_proc
    }

    logging.info(f"🚀 Both phases started! Monitoring {len(processes)} processes...")

    try:
        while processes:
            for name, process in list(processes.items()):
                if not monitor_process(process, name):
                    del processes[name]
                    logging.info(f"📊 Remaining processes: {len(processes)}")

            if processes:
                time.sleep(5)  # Check every 5 seconds

    except KeyboardInterrupt:
        logging.info("🛑 Received interrupt signal, shutting down gracefully...")

        # Send SIGTERM to all processes
        for name, process in processes.items():
            logging.info(f"🛑 Terminating {name}...")
            process.terminate()

        # Wait for processes to terminate
        for name, process in processes.items():
            try:
                process.wait(timeout=10)
                logging.info(f"✅ {name} terminated gracefully")
            except subprocess.TimeoutExpired:
                logging.warning(f"⚠️ {name} didn't terminate gracefully, forcing...")
                process.kill()

        logging.info("🛑 All processes terminated")
        return 0

    logging.info("🎉 All migration phases completed!")
    return 0


if __name__ == '__main__':
    sys.exit(main()) 