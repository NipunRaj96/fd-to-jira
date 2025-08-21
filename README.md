# Freshdesk Ticket Extraction Pipeline

A robust, production-ready system for extracting ticket details, conversations, and attachments from Freshdesk using a producer-consumer architecture with automatic retry mechanisms and URL refresh capabilities.

## 🎯 Overview

This pipeline extracts comprehensive data from Freshdesk tickets including:
- **Ticket Details**: Basic ticket information, status, priority, etc.
- **Conversations**: All ticket conversations and comments
- **Ticket Attachments**: Files attached directly to tickets
- **Conversation Attachments**: Files attached to individual conversations
- **User Information**: Contact and agent details

## 🏗️ Architecture

### Producer-Consumer Pattern
- **1 Producer**: `details_producer.py` - Orchestrates data extraction
- **3 Consumers**: Process different data types concurrently
  - `attachments_consumer.py` - Downloads ticket attachments
  - `conversations_consumer.py` - Processes conversation data
  - `conversation_attachments_consumer.py` - Downloads conversation attachments

### Data Flow
```
CSV Input → Producer → Migration Store → Consumers → Local Storage
```

## 📁 Important Files

### Core Pipeline Files
- **`details_producer.py`** - Main orchestrator, fetches ticket data from Freshdesk API
- **`attachments_consumer.py`** - Downloads ticket-level attachments
- **`conversations_consumer.py`** - Processes and stores conversation data
- **`conversation_attachments_consumer.py`** - Downloads conversation attachments

### Support Files
- **`extract_ticket_details.py`** - Core API interaction logic with SSL handling
- **`download_attachments.py`** - File download utilities with retry mechanisms
- **`migration_store.py`** - Thread-safe state management for processing status
- **`migration_store.py`** - Centralized data storage and retrieval

### Utility Scripts
- **`verify_attachments.py`** - Verifies download completeness and identifies mismatches
- **`reprocess_mismatched_ticket_attachments.py`** - Repairs missing ticket attachments
- **`reprocess_mismatched_conv_attachment.py`** - Repairs missing conversation attachments
- **`fetch_all_users.py`** - Extracts user/contact information

### Configuration
- **`.env`** - Environment variables and API credentials
- **`storage_config.py`** - Storage directory configuration

## 🚀 Quick Start

### 1. Environment Setup
```bash

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
Create `.env` file with your Freshdesk credentials:
```bash
FRESHDESK_DOMAIN="your-domain.freshdesk.com"
FRESHDESK_API_KEY="your-api-key"
TICKET_IDS_CSV_FILE="your-tickets.csv"
FRESH="y"  # y=active tickets first, n=archived tickets first
```

### 3. Prepare Input Data
Create a CSV file with ticket IDs:
```csv
ticket_id
12345
12346
12347
```

### 4. Run the Pipeline
```bash
# Start producer in background
python3 details_producer.py &

# Wait for producer to initialize and create initial data files
sleep 8

# Start all consumers simultaneously
python3 attachments_consumer.py &
python3 conversations_consumer.py &
python3 conversation_attachments_consumer.py &

# Wait for all processes to start
sleep 3

# Show running processes
ps aux | grep -E "(details_producer|attachments_consumer|conversations_consumer|conversation_attachments_consumer)" | grep -v grep
```

## 📊 Pipeline Execution

### Phase 1: Data Extraction (Producer)
- Reads CSV file with ticket IDs
- Fetches ticket data from Freshdesk API
- Stores metadata in JSON files
- Updates migration store with processing status

### Phase 2: Data Processing (Consumers)
- **Attachments Consumer**: Downloads ticket attachments
- **Conversations Consumer**: Processes conversation data
- **Conversation Attachments Consumer**: Downloads conversation attachments

### Phase 3: Verification
- Run `verify_attachments.py` to check completeness
- Identify any missing files or mismatches

## ⚙️ Configuration Options

### Environment Variables (.env)
```bash
# Required
FRESHDESK_DOMAIN="your-domain.freshdesk.com"
FRESHDESK_API_KEY="your-api-key"
TICKET_IDS_CSV_FILE="tickets.csv"

# Optional
FRESH="y"                    # y=active first, n=archived first
WORKERS=5                    # Number of concurrent workers
MAX_RETRIES=3               # Download retry attempts
DELAY_BETWEEN_REQUESTS=0.2  # Seconds between API calls
```

### Performance Tuning
- **Workers**: Increase for faster processing (5-15 recommended)
- **Delays**: Reduce for speed, increase for stability
- **Retries**: Balance between success rate and processing time

## 🔍 Monitoring and Verification

### Check Pipeline Status
```bash
# View running processes
ps aux | grep -E "(details_producer|attachments_consumer|conversations_consumer|conversation_attachments_consumer)" | grep -v grep

# Monitor logs in real-time
tail -f details_producer.log
tail -f attachments_consumer.log
tail -f conversations_consumer.log
tail -f conversation_attachments_consumer.log
```

### Verify Data Completeness
```bash
# Check attachment download status
python3 verify_attachments.py

# Expected output: 100% success rate for both ticket and conversation attachments
```

## 🚨 Troubleshooting

### Common Issues and Solutions

#### 1. SSL Certificate Errors
**Symptoms**: `SSLCertVerificationError` or SSL-related warnings
**Solution**: SSL handling is already configured in the codebase
**Prevention**: Ensure corporate firewall allows HTTPS connections

#### 2. Rate Limiting
**Symptoms**: 429 HTTP errors or slow processing
**Solution**: Reduce worker count or increase delays
**Command**: Modify `WORKERS` in `.env` or reduce `DELAY_BETWEEN_REQUESTS`

#### 3. URL Expiry
**Symptoms**: 403 Forbidden errors during downloads
**Solution**: Use reprocessing scripts to refresh URLs
**Commands**:
```bash
# For missing conversation attachments
python3 reprocess_mismatched_conv_attachment.py

# For missing ticket attachments
python3 reprocess_mismatched_ticket_attachments.py
```

#### 4. Missing Attachments
**Symptoms**: Verification shows <100% success rate
**Solution**: Run appropriate reprocessing script
**Verification**: Re-run `verify_attachments.py` after reprocessing

### Error Recovery

#### If Producer Fails
```bash
# Stop all processes
pkill -f "details_producer|attachments_consumer|conversations_consumer|conversation_attachments_consumer"

# Check logs for errors
tail -n 50 details_producer.log

# Restart pipeline
python3 details_producer.py &
sleep 8
python3 attachments_consumer.py & python3 conversations_consumer.py & python3 conversation_attachments_consumer.py &
```

#### If Consumers Fail
```bash
# Check specific consumer logs
tail -n 50 attachments_consumer.log
tail -n 50 conversations_consumer.log
tail -n 50 conversation_attachments_consumer.log

# Restart failed consumers
python3 attachments_consumer.py &
python3 conversations_consumer.py &
python3 conversation_attachments_consumer.py &
```

#### If Downloads Fail
```bash
# Verify current status
python3 verify_attachments.py

# Reprocess missing attachments
python3 reprocess_mismatched_ticket_attachments.py
python3 reprocess_mismatched_conv_attachment.py
```

## 📈 Performance Optimization

### For Large Datasets (1000+ tickets)
- **Increase workers**: Set `WORKERS=10-15` in `.env`
- **Reduce delays**: Set `DELAY_BETWEEN_REQUESTS=0.1`
- **Monitor rate limits**: Watch for 429 errors in logs

### For Small Datasets (<100 tickets)
- **Default settings**: `WORKERS=5`, `DELAY_BETWEEN_REQUESTS=0.2`
- **Faster processing**: Minimal configuration needed

## 🔒 Security Considerations

### API Key Management
- Store API keys in `.env` file (never commit to version control)
- Use environment-specific `.env` files for different environments
- Rotate API keys regularly

### Data Privacy
- Downloaded attachments are stored locally
- Ensure proper access controls on local storage
- Consider data retention policies

## 📋 Output Structure

```
project/
├── ticket_attachments/           # Ticket attachment metadata
├── conversations/                # Conversation data
├── conversation_attachments/     # Conversation attachment metadata
├── attachments/                  # Downloaded files
│   ├── ticket_id_1/
│   ├── ticket_id_2/
│   └── ...
├── migration/                    # Processing status tracking
└── logs/                        # Execution logs
```

## 🎯 When to Use This Pipeline

### Use Cases
- **Data Migration**: Moving from Freshdesk to another system
- **Compliance**: Data retention and audit requirements
- **Analysis**: Offline analysis of ticket data
- **Backup**: Creating local backups of Freshdesk data
- **Integration**: Feeding data into other systems

### When NOT to Use
- **Real-time Processing**: This is a batch processing system
- **Frequent Updates**: Designed for one-time or periodic extractions
- **Small Data Sets**: For <10 tickets, manual extraction may be faster

### Regular Maintenance
- **Monitor Logs**: Check for errors and warnings
- **Verify Data**: Run verification scripts regularly
- **Update Dependencies**: Keep Python packages updated
- **Review Rate Limits**: Monitor Freshdesk API usage

### Getting Help
1. **Check Logs**: Most issues are logged with detailed error messages
2. **Verify Configuration**: Ensure `.env` file is properly configured
3. **Check Network**: Verify connectivity to Freshdesk
4. **Review Documentation**: This README and inline code comments
