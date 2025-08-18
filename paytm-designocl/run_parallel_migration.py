#!/usr/bin/env python3
"""
Parallel Migration Runner

Runs all migration phases in parallel to avoid metadata expiration issues.
Freshdesk attachment URLs expire after 30 minutes, so we need to download
everything quickly after metadata collection.

Phases:
1. details_producer.py - Extract ticket data and metadata
2. attachments_consumer.py - Download ticket attachments
3. conversations_consumer.py - Download conversation attachments

All phases run simultaneously to maximize speed and minimize expiration.
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
            logging.FileHandler('parallel_migration.log', mode='a', encoding='utf-8')
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


def main():
    """Main parallel migration runner"""
    setup_logging()
    logging.info("🚀 Starting Parallel Migration Runner")
    
    # Check if required scripts exist
    required_scripts = [
        'details_producer.py',
        'attachments_consumer.py', 
        'conversations_consumer.py'
    ]
    
    for script in required_scripts:
        if not Path(script).exists():
            logging.error(f"❌ Required script {script} not found!")
            return 1
    
    # Start all phases in parallel
    processes = {}
    
    # Phase 1: Details Producer (if not already completed)
    if not Path('migration/ticket_details.json').exists():
        details_proc = start_phase('details_producer.py', 'Phase 1: Details Producer')
        if details_proc:
            processes['details_producer'] = details_proc
    else:
        logging.info("✅ Phase 1 already completed, skipping...")
    
    # Phase 2: Attachments Consumer
    attachments_proc = start_phase('attachments_consumer.py', 'Phase 2: Attachments Consumer')
    if attachments_proc:
        processes['attachments_consumer'] = attachments_proc
    
    # Phase 3: Conversations Consumer  
    conversations_proc = start_phase('conversations_consumer.py', 'Phase 3: Conversations Consumer')
    if conversations_proc:
        processes['conversations_consumer'] = conversations_proc
    
    if not processes:
        logging.error("❌ No processes started!")
        return 1
    
    logging.info(f"🚀 All phases started! Monitoring {len(processes)} processes...")
    
    # Monitor all processes
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