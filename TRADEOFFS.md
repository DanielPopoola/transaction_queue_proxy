# Architecture Tradeoffs

## Retry Strategy

**Decision**: Exponential backoff with jitter (60s → 120s → 240s) and max 5 retries.

**Why exponential?** Prevents thundering herd when downstream recovers. If 1000 messages failed simultaneously, fixed retry would slam the service with 1000 requests at once. Exponential backoff spreads load over time.

**Why jitter?** Randomizes retry timing (±20%) to prevent synchronized retries from different workers converging on the same timestamp. Critical for distributed systems.

**Why dead-letter queue?** Permanent failures (bad data, 4xx errors) shouldn't retry forever. After 5 attempts spanning ~8 minutes, move to dead-letter for manual investigation. Preserves queue throughput.

## Persistence Layer

**Decision**: PostgreSQL with database-first writes.

**Why PostgreSQL over Redis?** Durability guarantees. Redis (in-memory) loses data on crash unless configured with AOF/RDB, which adds complexity. PostgreSQL provides ACID transactions and survives crashes by default. For financial transactions, losing a $10,000 payment is unacceptable.

**Trade-off**: Disk I/O latency (~1-5ms) vs in-memory speed (~0.1ms). Acceptable cost for guaranteed persistence. Current bottleneck is downstream HTTP calls (50-200ms), not database writes.

**Why write-before-process?** Every message is persisted before calling downstream service. If server crashes mid-processing, crash recovery marks stuck messages as failed and retries them. Zero message loss.

## At-Least-Once vs Exactly-Once Delivery

**Decision**: At-least-once delivery with idempotency.

**Why not exactly-once?** True exactly-once requires distributed transactions between Kafka, database, and downstream service - significantly more complex and fragile. Requires two-phase commit or saga patterns.

**Simplification**: Accept potential duplicates. Handle with:
1. Database idempotency: `ON CONFLICT (transaction_id) DO NOTHING` prevents duplicate saves
2. Kafka offset commit after successful processing
3. Downstream service must be idempotent (outside our control, but documented requirement)

**Financial systems reality**: Prefer duplicate over loss. A duplicate transaction can be detected and refunded. A lost transfer cannot be recovered.

## Performance vs Durability

**Current design**: Prioritizes durability over throughput.

**Bottlenecks**:
1. Consumer processes messages sequentially (one at a time)
2. Synchronous database write before each HTTP call
3. Retry worker limited to 5 concurrent retries (semaphore)

**Trade-off rationale**: For 10-100 messages/second, this design is sufficient. Sequential processing simplifies debugging and crash recovery. Database writes add ~2ms latency but guarantee no loss.

**Scaling path (if needed)**: Decouple consumption from processing. Consumer writes to database only; separate worker pool pulls from database and processes. This enables horizontal scaling (multiple workers) and better Kafka throughput. Current design handles expected load with simpler codebase.

## Observability

**Decision**: REST API with basic metrics, no distributed tracing.

**Metrics exposed**:
- Queue counts by status (actionable: high dead-letter count signals downstream issues)
- Health check (database connectivity)
- Transaction history (debugging failed transactions)
- Replay endpoint (manual recovery from dead-letter)

**What's missing**: Real-time alerting, Prometheus/Grafana integration, distributed tracing (correlating Kafka message → database → downstream). These add dependencies (Prometheus, Jaeger) and operational complexity.

**Trade-off**: Simple monitoring sufficient for MVP. Logs provide debugging context. For production, integrate Prometheus metrics and alerting (e.g., alert if dead-letter count > 10).

**Replay design**: Manual intervention for dead-letter transactions. Operator reviews error, fixes root cause (bad data format, downstream bug), then replays. Automated replay could create infinite loops if root cause persists.
