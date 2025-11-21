# Transaction Queue Proxy

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

A resilient and observable asynchronous queuing layer for financial transactions, inspired by Uber’s Kafka Consumer Proxy architecture. This service acts as a buffered, fault-tolerant proxy between a Kafka message broker and downstream transaction processors, ensuring reliable delivery even when downstream services are slow or unavailable.

---

## Core Concepts

- **Decoupling**: The proxy decouples the message *ingestion* from Kafka from the *processing* of those messages. A persistent database queue acts as a buffer, allowing the service to absorb traffic spikes and protect downstream services.
- **Durability**: By storing messages in PostgreSQL before processing, the system guarantees that no transaction is lost, even if the application crashes.
- **Observability**: Key metrics about queue depth, message status, and retries are exposed via an API endpoint, providing visibility into the system's health.
- **Idempotency**: The proxy database automatically handles duplicate messages from Kafka, ensuring that a given transaction is only queued for processing once.

## Architecture

The entire stack is managed via `docker-compose` and consists of the following services:

- **`app`**: The main Python application, containing the Kafka consumer, processor workers, and the management API.
- **`postgres`**: A PostgreSQL database that serves as the persistent queue for messages and their state.
- **`kafka` & `zookeeper`**: The message broker for ingesting transactions.
- **`mock_downstream`**: A simple Flask-based mock service that simulates a real downstream transaction processor. It is configured to randomly succeed or fail, allowing for realistic testing of the proxy's retry logic.

### Visual Flow

```ascii
                               +-----------------+
    (External) ~~~> Kafka ~~~> |    Consumer     |
                               | (in 'app' svc)  |
                               +-------+---------+
                                       |
                                       | .save_pending()
                                       v
                          +--------------------------+
                          |      PostgreSQL DB       |
                          | (Persistent Message Queue) |
                          +------------+-------------+
                                       |
            +--------------------------+---------------------------+
            | .read_pending()                                      | .read_failed()
            v                                                      v
    +-------+---------+                                    +-------+---------+
    |    Processor    |                                    |   Retry Worker  |
    | (in 'app' svc)  |                                    | (in 'app' svc)  |
    +-------+---------+                                    +-------+---------+
            |                                                      |
            | .process()                                           | .requeue_if_ready()
            v                                                      |
    +-------+---------+                                            |
    |  Mock Downstream| ~~~> (Success) ~~~> .mark_success() ~~~> (END)
    |     Service     |                                            |
    +-----------------+ ~~~> (Failure) ~~~> .mark_failed() ~~~~~>--+
```

## Getting Started

This project is designed to be run as a complete, containerized stack using Docker.

### Prerequisites
- [Docker](https://www.docker.com/get-started) and Docker Compose
- Python 3.12+ and [uv](https://github.com/astral-sh/uv) (for running local scripts)

### Running the Full Stack
The recommended way to run the project is with Docker Compose, which orchestrates all the services defined in the architecture.

1.  **Build and Start the Services:**
    From the root of the project, run:
    ```bash
    docker-compose up --build -d
    ```
    This command will build the `app` and `mock_downstream` images and start all services in detached mode.

2.  **Check the Logs:**
    To see the live output from the application, including the consumer and processor workers:
    ```bash
    docker-compose logs -f app
    ```

### Interacting with the Service

Once the stack is running, you can test its functionality.

1.  **Produce Test Messages:**
    A helper script is provided to send sample messages to the Kafka topic.
    ```bash
    uv run python scripts/produce_test_messages.py
    ```
    This will send several messages, some of which will cause the `mock_downstream` service to fail, triggering the retry mechanism.

2.  **Check Service Health and Metrics:**
    Use the API to monitor the system.
    - **Health Status**: [http://localhost:8000/status](http://localhost:8000/status)
    - **Queue Metrics**: [http://localhost:8000/metrics](http://localhost:8000/metrics)
    - **Recent Transactions**: [http://localhost:8000/transactions](http://localhost:8000/transactions)

## API Endpoints

- `GET /`: Basic service information.
- `GET /metrics`: Exposes queue metrics (e.g., `pending`, `success`, `failed` counts) in JSON format.
- `GET /status`: A health check endpoint that verifies connectivity to the database.
- `GET /transactions`: Returns a list of the most recent transactions and their status.
- `POST /replay/{transaction_id}`: Manually requeue a `failed` or `dead_letter` message for processing.

## Testing

The project uses `pytest`. To run the test suite:

```bash
# Install dev dependencies
uv sync --dev

# Run tests
pytest
```

## CI/CD Pipeline

A continuous integration and deployment pipeline for this service would typically include the following stages:

1.  **Lint & Test**:
    - Run `ruff check .` to check for linting errors.
    - Run `pytest` to execute the unit and integration test suite.
2.  **Build Docker Image**:
    - Build the application image: `docker build -t my-registry/transaction-queue-proxy:${GIT_SHA} .`
3.  **Push to Registry**:
    - Authenticate with a container registry (e.g., Docker Hub, AWS ECR).
    - Push the tagged image: `docker push my-registry/transaction-queue-proxy:${GIT_SHA}`
4.  **Deploy**:
    - Update the running service to use the new image (e.g., using `kubectl set image`, updating an ECS task definition, or via a GitOps workflow).

## Future Extensions

This project provides a solid foundation that can be extended in several ways:

- **Worker Pools**: To handle higher message volume, the `Processor` can be scaled out into a pool of workers. This would involve running multiple `Processor` tasks or containers that all pull from the same PostgreSQL queue, increasing throughput.
- **Priority Queues**: A `priority` field could be added to the `messages` table. The `Processor` could then be modified to fetch high-priority messages before standard ones.
- **Enhanced Observability**: While basic metrics are available, the next step would be to export them to Prometheus and build a Grafana dashboard for rich, time-series visualizations of queue depth, processing latency, and error rates.
- **Multi-Consumer Balancing**: For very high-volume Kafka topics, the number of `Consumer` instances can be increased (up to the number of partitions in the topic) to scale message ingestion.
