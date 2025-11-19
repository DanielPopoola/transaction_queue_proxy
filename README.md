# Transaction Queue Proxy

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

A resilient and observable asynchronous queuing layer for financial transactions, inspired by Uber’s Kafka Consumer Proxy architecture.

This service acts as a buffered, fault-tolerant proxy between a Kafka message broker and downstream transaction processors. It ensures that transaction events are delivered reliably with controlled concurrency and backpressure handling, protecting fragile consumers from overloads or downtime.

---

## Architecture

The proxy is built on an asynchronous, multi-worker architecture using Python's `asyncio`.

**Core Components:**
- **Message Broker**: Kafka (managed via `docker-compose`)
- **Application Framework**: FastAPI
- **Internal Queue/State Store**: PostgreSQL (for persistence)
- **HTTP Client**: `httpx` for async requests to downstream services

**Data Flow:**
1.  **Consumer**: The `Consumer` worker connects to a specified Kafka topic, ingests messages, and immediately stores them in a PostgreSQL database with a `pending` status. This ensures that no message is lost, even if the application crashes.
2.  **Processor**: The `Processor` worker fetches `pending` messages from the PostgreSQL database and attempts to deliver them to the configured downstream service.
    - On **success** (HTTP 2xx), the message status is updated to `success`.
    - On **failure** (HTTP 4xx/5xx or network error), the status is updated to `failed`, and the `retry_count` is incremented.
3.  **Retry Worker**: A separate `RetryWorker` periodically scans for `failed` messages. It uses an exponential backoff strategy to determine when a message should be retried.
    - If a message is eligible for retry, its status is reset to `pending` to be picked up by the `Processor` again.
    - If a message exceeds its maximum retry limit, its status is set to `dead_letter`.
4.  **API & Metrics**: A FastAPI server runs alongside the workers to expose health, metrics, and control endpoints.

This design decouples message ingestion from processing, providing durability and resilience against downstream failures.

## Features

- **Durable Queuing**: Persists all incoming messages to a PostgreSQL database before processing.
- **At-Least-Once Delivery**: Guarantees that messages will be delivered at least once to the downstream service.
- **Automatic Retries with Exponential Backoff**: Automatically retries failed messages with increasing delays to handle transient downstream issues gracefully.
- **Dead-Letter Queue (DLQ)**: Messages that fail repeatedly are moved to a dead-letter state for manual inspection and replay.
- **Observability**:
    - Exposes key metrics (queue size, message statuses, retries) via a `/metrics` endpoint for simple
    observability
- **Manual Replay**: API endpoint to manually trigger a replay of failed or dead-lettered messages.
- **Containerized**: Fully containerized with `docker-compose` for easy setup of the application, Kafka, Postgres, and a mock downstream service.

## API Endpoints

- `GET /metrics`: Exposes application and queue metrics in Prometheus format.
- `GET /status`: Get health status of system
- `POST /replay/{message_id}`: Manually requeue a `failed` or `dead_letter` message for processing.

## Getting Started

### Prerequisites

- [Docker](https://www.docker.com/get-started) and Docker Compose
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (for Python package management)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/DanielPopoola/transaction_queue_proxy
    cd transaction-queue-proxy
    ```

2.  **Install Python dependencies using `uv`:**
    ```bash
    uv sync
    ```

### Running the Application

The entire stack (app, Kafka, Zookeeper, Postgres, and a mock downstream service) can be started using Docker Compose.

1.  **Build and start the services:**
    ```bash
    docker-compose up --build -d
    ```

2.  **Check the logs to ensure everything is running:**
    ```bash
    docker-compose logs -f app
    ```
    You should see logs from the consumer, processor, and retry worker.

3.  **Produce test messages (Optional):**
    A script is provided to send sample messages to the Kafka topic.
    ```bash
    uv run python scripts/produce_test_messages.py
    ```

4.  **Access the API:**
    - **Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
    - **Metrics**: [http://localhost:8000/metrics](http://localhost:8000/metrics)

## Configuration

The application is configured via environment variables. See `src/config.py` for all available options. Key variables include:

- `KAFKA_BOOTSTRAP_SERVERS`: Address of the Kafka brokers.
- `KAFKA_TOPIC`: The topic to consume messages from.
- `DATABASE_URL`: Connection string for the PostgreSQL database.
- `DOWNSTREAM_URL`: The URL of the service to which messages should be sent.
- `MAX_RETRIES`: Maximum number of times to retry a failed message.

These can be set in a `.env` file or directly in the `docker-compose.yml` environment section.

## Running Tests

The project uses `pytest` for testing.

1.  **Ensure test dependencies are installed:**
    ```bash
    uv sync --dev
    ```

2.  **Run the test suite:**
    ```bash
    pytest
    ```

## Project Structure

```
transaction-queue-proxy/
├── README.md
├── .gitignore
├── docker-compose.yml
├── pyproject.toml
├── schema.sql
├── src/
│   ├── main.py              # FastAPI app entrypoint & worker orchestration
│   ├── api.py               # API endpoints (dashboard, metrics, replay)
│   ├── consumer.py          # Kafka consumer logic
│   ├── processor.py         # Downstream delivery logic
│   ├── retry_worker.py      # Backoff + replay logic
│   ├── storage.py           # PostgreSQL persistence logic
│   ├── config.py            # Configuration models
│   ├── metrics.py           # Prometheus metrics setup
│   └── backoff.py           # Exponential backoff utility
└── tests/
    ├── test_processor.py
    ├── test_retry_worker.py
    └── ...
```
