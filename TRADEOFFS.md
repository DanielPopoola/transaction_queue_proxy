# Trade-Offs and Design Decisions

This document outlines the key design trade-offs made in the `transaction-queue-proxy` project.

### 1. Delivery Guarantees: At-Least-Once vs. Exactly-Once

- **Decision**: The system is designed for **at-least-once delivery**.
- **Rationale**: In financial systems, losing a transaction is typically unacceptable. We prioritize durability over avoiding duplicates. The core workflow ensures this by first persisting every message consumed from Kafka into the local database *before* attempting to process and forward it to the downstream service.
- **Trade-Off**: This model accepts that a message might be delivered more than once. For example, if the service successfully sends a message to the downstream API but crashes before it can update the message's status to `success` in its own database, it will re-send the same message upon restart.
- **Mitigation**: The responsibility for handling duplicates is shifted to the downstream services, which are expected to be **idempotent**. They should be able to receive the same transaction multiple times without creating duplicate financial records (e.g., by checking for a unique transaction ID).

### 2. Retry Strategy: Exponential Backoff

- **Decision**: Failed messages are retried with **exponential backoff**.
- **Rationale**: When a downstream service fails, retrying requests immediately and aggressively can lead to a "thundering herd" problem, where thousands of simultaneous retries overwhelm the service as it attempts to recover. Exponential backoff introduces progressively longer delays between retries for a given message.
- **Trade-Off**: This strategy increases message delivery latency for failed transactions compared to a fixed, short-delay retry mechanism. However, it significantly improves the stability of the entire system by giving downstream services breathing room to recover from transient failures.

### 3. Persistence Layer: PostgreSQL Database

- **Decision**: A PostgreSQL database is used as the internal queue and state store.
- **Rationale**:
    - **Robustness & Scalability**: Unlike SQLite, PostgreSQL is a full-featured, client-server RDBMS designed for high concurrency. This is critical for future enhancements, such as horizontally scaling the proxy workers, which aligns with the project's stretch goals.
    - **Data Integrity**: PostgreSQL offers strong ACID-compliant transactional guarantees and advanced data integrity features required for mission-critical financial systems.
    - **Rich Feature Set**: It supports advanced data types, indexing, and functions that can be leveraged for future requirements like priority queues or more complex analytics.
- **Trade-Off**:
    - **Operational Overhead**: PostgreSQL requires a separate database server, which adds more operational complexity compared to a file-based database like SQLite. This is largely mitigated by using Docker Compose to manage the database lifecycle in development and production environments.

### 4. Performance: Decoupled Workers vs. Throughput

- **Decision**: The architecture decouples message ingestion (`Consumer`) from message delivery (`Processor`) using the database as a buffer.
- **Rationale**: This separation of concerns prevents the consumer from slowing down if the downstream service is latent. The consumer's only job is to pull messages from Kafka and write them to the local database, which is a very fast operation. The processor can then work through the queue at a pace the downstream service can handle.
- **Trade-Off**: This approach introduces a small amount of latency, as messages are written to and then read from the database instead of being passed directly in memory. The primary goal here is **resilience and stability**, not absolute minimum latency. For higher performance, the database could be replaced with a more performant storage, or workers could be scaled, but the current setup prioritizes simplicity.

### 5. Observability: Simple Metrics

- **Decision**: Observability is provided through a basic `/metrics` endpoint for Prometheus and a simple HTML dashboard.
- **Rationale**: The goal is to provide essential, at-a-glance visibility into the health and state of the queue. This includes queue depth, the number of messages in each state (`pending`, `failed`, `dead_letter`), and retry counts.
- **Trade-Off**: This approach does not include more advanced observability features like distributed tracing, detailed performance analysis of downstream calls, or rich, pre-built Grafana dashboards. It provides just enough information to understand the system's state without adding significant complexity to the initial build.
