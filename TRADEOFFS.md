# Trade-Offs and Design Decisions

### Delivery Guarantee & Idempotency

- **Goal**: Prefer duplication over message loss (at-least-once delivery), which is critical for financial transactions.
- **Implementation**:
    1.  Messages are first persisted to the database before being processed. This ensures no messages are lost if the service crashes.
    2.  The database insert uses `ON CONFLICT (transaction_id) DO NOTHING`. This provides **idempotency at the proxy level**, preventing duplicate jobs from being created if Kafka redelivers a message.
- **Trade-off**: While the proxy won't process the same job twice, it is still possible for a message to be delivered to the downstream service more than once (e.g., if a network error occurs after a successful delivery but before the job is marked as 'success'). Therefore, downstream services should still be idempotent.

### Retry Strategy

- **Goal**: Prevent the "thundering herd" problem where a recovering downstream service is overwhelmed by simultaneous retries.
- **Implementation**: A failed message is rescheduled for a future time using **exponential backoff**, which progressively increases the delay between retries.

### Performance & Scalability

- **Goal**: Decouple message consumption from processing to handle downstream slowness or failures without blocking the Kafka consumer.
- **Implementation**: The `Consumer` and `Processor` run as separate, concurrent workers with the database acting as a buffer between them. This allows the system to absorb spikes in traffic.

### Persistence

- **Goal**: Ensure durability of in-flight transactions across service restarts or crashes.
- **Implementation**: A PostgreSQL database is used as the state store for all messages and their statuses. A relational database was chosen for its robustness and to support future requirements (e.g., analytics, complex queries).

### Observability

- **Goal**: Provide simple, essential metrics for monitoring system health.
- **Implementation**: A `/metrics` endpoint exposes the status and count of messages in the queue (pending, failed, etc.).
