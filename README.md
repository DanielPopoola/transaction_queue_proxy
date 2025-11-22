# Transaction Queue Proxy

A resilient asynchronous queuing system for financial transactions that ensures no message is lost, even under failures or high load.

## What Does This Do?

Imagine you have a payment system that needs to process thousands of transactions. Sometimes your payment processor goes down, gets overloaded, or just returns errors. This proxy sits between your message queue (Kafka) and your payment processor, making sure:

- **No transaction is ever lost** (persisted to database immediately)
- **Failed transactions are retried automatically** (with smart backoff)
- **The system recovers from crashes** (crashed messages are detected and retried)
- **You can monitor everything** (REST API with metrics)

Think of it as a "safety net" for critical financial operations.

## Architecture

```
┌──────────┐         ┌─────────────────────────────────┐         ┌────────────┐
│  Kafka   │────────>│   Transaction Queue Proxy       │────────>│ Downstream │
│  Topic   │         │                                 │         │  Service   │
└──────────┘         │  ┌──────────┐   ┌───────────┐  │         └────────────┘
                     │  │ Consumer │   │ Processor │  │
                     │  └──────────┘   └───────────┘  │
                     │        │              │         │
                     │        └──────┬───────┘         │
                     │               ▼                 │
                     │        ┌────────────┐           │
                     │        │ PostgreSQL │           │
                     │        │  Storage   │           │
                     │        └────────────┘           │
                     │               ▲                 │
                     │               │                 │
                     │        ┌──────────────┐         │
                     │        │ Retry Worker │         │
                     │        └──────────────┘         │
                     │                                 │
                     │        ┌──────────────┐         │
                     │        │  Metrics API │         │
                     │        └──────────────┘         │
                     └─────────────────────────────────┘
```

### Component Breakdown

1. **Kafka Consumer** - Pulls transaction messages from Kafka
2. **Storage Layer** - PostgreSQL database that persists every message state
3. **Processor** - Sends transactions to downstream service with error handling
4. **Retry Worker** - Background task that retries failed messages
5. **Metrics API** - REST endpoints for monitoring and management

### Message Flow

```
1. Message arrives from Kafka
   ↓
2. Save to database (status: 'pending')
   ↓
3. Mark as 'processing'
   ↓
4. Send to downstream service
   ↓
   ├─ Success? → Mark as 'success' → Commit Kafka offset
   │
   ├─ Transient error (5xx, timeout)? → Mark as 'failed', schedule retry
   │
   └─ Permanent error (4xx) or max retries? → Mark as 'dead_letter'
```

### Database Schema

```sql
CREATE TABLE messages (
    transaction_id VARCHAR(255) PRIMARY KEY,  -- Unique transaction ID
    payload JSONB,                             -- Transaction data
    status VARCHAR(20),                        -- pending | processing | success | failed | dead_letter
    retry_count INTEGER DEFAULT 0,             -- How many times we've retried
    error_message TEXT,                        -- Last error that occurred
    next_retry_at TIMESTAMPTZ,                -- When to retry next
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Retry Strategy

Uses **exponential backoff with jitter**:

```
Attempt 1: ~60 seconds  (1 minute)
Attempt 2: ~120 seconds (2 minutes)
Attempt 3: ~240 seconds (4 minutes)
Attempt 4: ~480 seconds (8 minutes)
Attempt 5: ~960 seconds (16 minutes)
```

After 5 failures, the message moves to `dead_letter` status for manual investigation.

**Why exponential?** If 100 messages fail at once, you don't want all 100 retrying simultaneously when the service recovers. Spreading them out prevents overwhelming the downstream service.

**Why jitter?** Adds randomness (±20%) to prevent synchronized retries from different workers colliding.

## Prerequisites

- **Docker & Docker Compose** - For running all services
- **Python 3.12** - For local development
- **uv** - Fast Python package manager (optional but recommended)

## Quick Start with Docker

This is the easiest way to run the entire system:

```bash
# 1. Clone the repository
git clone https://github.com/DanielPopoola/transaction_queue_proxy
cd transaction-queue-proxy

# 2. Create environment file
cp .env.example .env

# 3. Start all services (Kafka, PostgreSQL, app, mock downstream)
docker-compose up --build

# 4. In another terminal, send test messages
docker-compose exec app python scripts/produce_test_messages.py

# 5. Check the metrics
curl http://localhost:8000/metrics
```

### What Just Happened?

Docker Compose started:
- **PostgreSQL** (port 5432) - Database for message persistence
- **Zookeeper** - Kafka dependency
- **Kafka** (port 29092) - Message broker
- **Mock Downstream** (port 8001) - Simulates payment processor (80% success rate)
- **App** (port 8000) - The transaction queue proxy

## Local Development with uv

For active development, you'll want to run components individually:

### 1. Start Infrastructure

```bash
# Start only Kafka, PostgreSQL, and mock downstream
docker-compose up postgres kafka zookeeper mock_downstream
```

### 2. Set Up Python Environment

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync

# Activate the virtual environment
source .venv/bin/activate
```

### 3. Set Environment Variables

Create a `.env` file:

```bash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=transactions
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

KAFKA_BROKER=localhost:29092

DOWNSTREAM_URL=http://localhost:8001/process

MAX_RETRIES=5
BASE_DELAY=60
MAX_DELAY=3600
MAX_CONCURRENT_RETRIES=5
```

### 4. Run the Application

```bash
python -m src.main
```

### 5. Send Test Messages

In another terminal:

```bash
python scripts/produce_test_messages.py
```

## Running Tests

### With Docker (Integration Tests)

```bash
# Start test database
docker-compose up postgres

# Run tests
uv run pytest -v
```

### Locally with uv

```bash
# Make sure PostgreSQL is running
docker-compose up postgres -d

# Run tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_storage.py -v

# Run with coverage
uv run pytest --cov=src tests/
```

### Test Structure

```
tests/
├── conftest.py              # Fixtures (database pool, storage, processor)
├── test_storage.py          # Database operations
├── test_processor.py        # Message processing logic
└── test_retry_worker.py     # Retry mechanism
```

## API Endpoints

Once running, access these endpoints:

### GET `/metrics`
```bash
curl http://localhost:8000/metrics
```

Response:
```json
{
  "pending": 5,
  "processing": 2,
  "success": 143,
  "failed": 7,
  "dead_letter": 1,
  "total": 158
}
```

### GET `/status`
```bash
curl http://localhost:8000/status
```

Response:
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2024-11-22T10:30:00Z"
}
```

### GET `/transactions?limit=20`
```bash
curl http://localhost:8000/transactions?limit=10
```

Response:
```json
[
  {
    "transaction_id": "TX-TEST-001",
    "status": "success",
    "retry_count": 0,
    "error_message": null,
    "created_at": "2024-11-22T10:25:00Z",
    "updated_at": "2024-11-22T10:25:01Z"
  },
  ...
]
```

### POST `/replay/{transaction_id}`
```bash
curl -X POST http://localhost:8000/replay/TX-FAILED-123
```

Resets a `dead_letter` transaction back to `pending` so it gets retried.

## Monitoring in Action

### Watch Logs

```bash
# All services
docker-compose logs -f

# Just the app
docker-compose logs -f app

# Just Kafka
docker-compose logs -f kafka
```

### Example Log Flow

```
INFO - Received transaction TX-001 from Kafka
INFO - Processing transaction TX-001, attempt 1
INFO - Transaction TX-001 succeeded
INFO - Committed offset for transaction TX-001

WARN - Transaction TX-002 failed with network error: TimeoutError
WARN - Transaction TX-002 will retry at 2024-11-22 10:31:00. Retry count: 1/5

INFO - Found 3 messages to retry
INFO - Processing transaction TX-002, attempt 2
INFO - Transaction TX-002 succeeded
```

## Project Structure

```
transaction-queue-proxy/
├── src/
│   ├── main.py              # Application entry point
│   ├── config.py            # Configuration management
│   ├── consumer.py          # Kafka consumer
│   ├── processor.py         # Message processing logic
│   ├── storage.py           # Database operations
│   ├── retry_worker.py      # Background retry task
│   ├── backoff.py           # Exponential backoff calculation
│   ├── api.py               # REST API endpoints
│   └── metrics.py           # Metrics service
├── tests/
│   ├── conftest.py          # Test fixtures
│   ├── test_storage.py      # Storage tests
│   ├── test_processor.py    # Processor tests
│   └── test_retry_worker.py # Retry worker tests
├── scripts/
│   └── produce_test_messages.py  # Kafka producer for testing
├── docker-compose.yml       # Docker services configuration
├── schema.sql               # Database schema
├── pyproject.toml           # Python dependencies
├── TRADEOFFS.md            # Architecture decisions explained
└── README.md               # This file
```

## Key Design Decisions

### 1. Why PostgreSQL instead of Redis?

**Durability over speed.** Financial transactions cannot be lost. PostgreSQL provides ACID guarantees and survives crashes by default. Redis requires additional configuration (AOF/RDB) for persistence.

### 2. Why At-Least-Once delivery?

**Simplicity and safety.** Exactly-once delivery requires distributed transactions across Kafka, database, and downstream service - much more complex. We accept potential duplicates and rely on idempotency (`ON CONFLICT DO NOTHING` in database).

### 3. Why Sequential Processing?

**Current design processes one message at a time.** This trades throughput for simplicity and easier crash recovery. For higher throughput, you can add a worker pool (see TRADEOFFS.md).

### 4. Why Separate Retry Worker?

**Decouples consumption from retries.** The consumer focuses on new messages from Kafka. The retry worker independently scans the database for failed messages that are ready to retry. This prevents retry logic from blocking new message consumption.

## Troubleshooting

### "Connection refused" when starting app

Kafka takes 20-30 seconds to fully start. The app has retry logic, but if it fails:

```bash
# Check Kafka is healthy
docker-compose ps

# Restart just the app
docker-compose restart app
```

### Messages aren't being processed

```bash
# Check if messages are in Kafka
docker-compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic transactions.incoming \
  --from-beginning

# Check database
docker-compose exec postgres psql -U postgres -d transactions \
  -c "SELECT transaction_id, status, error_message FROM messages ORDER BY created_at DESC LIMIT 10;"
```

### High dead_letter count

Check the error messages:

```bash
curl http://localhost:8000/transactions?limit=50 | jq '.[] | select(.status=="dead_letter")'
```

Common causes:
- Downstream service is down completely (all 5xx errors)
- Bad message format (4xx errors)
- Network issues between app and downstream service

## License

MIT