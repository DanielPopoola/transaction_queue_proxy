import random
from datetime import UTC, datetime, timedelta


def calculate_next_retry(
        retry_count: int,
        base_delay: int = 60,
        max_delay: int = 3600,
        jitter: float = 0.2
) -> datetime:
    delay = base_delay * (2 ** retry_count)
    delay = min(delay, max_delay)
    jitter_amount = delay * jitter
    delay = delay + random.uniform(-jitter_amount, jitter_amount)
    delay = max(0, delay)
    return datetime.now(UTC) + timedelta(seconds=delay)