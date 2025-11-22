# Performance Baseline (Phase 0)

**Test Date:** 2025-11-22
**Test Load:** 1M messages @ 12,444 msg/sec for 80 seconds

## Current Capacity
- **Throughput:** 167 messages/sec
- **Latency (avg):** 19.9ms per message
- **Success Rate:** 80% (expected, per mock downstream)

## Bottleneck Analysis
| Operation | Avg Latency | % of Total |
|-----------|-------------|------------|
| DB Save | 5.0ms | 25% |
| Downstream API | 16.9ms | **85%** ← PRIMARY BOTTLENECK |
| DB Update | 6.7ms | 34% |

## Scaling Requirements
To handle 12,444 msg/sec:
- Current: 1 sequential consumer
- Required: ~250 parallel workers
- Scaling factor needed: **250x**

## Next Steps
1. Implement Phase 1 (Redis Queue) - decouple ingestion from processing
2. Target: 10x improvement (1,670 msg/sec)
3. Then Phase 5-6 for full horizontal scaling