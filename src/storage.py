import asyncpg
from datetime import datetime


class Storage:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def save_pending(self, transaction_id: str, payload: dict) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (transaction_id, payload, status)
                VALUES ($1, $2, 'pending')
                ON CONFLICT (transaction_id) DO NOTHING
                """,
                transaction_id, payload
            )

    async def mark_processing(self, transaction_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages 
                SET status = 'processing', 
                    updated_at = NOW()
                WHERE transaction_id = $1
                """,
                transaction_id
            )

    async def mark_success(self, transaction_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET status = 'success',
                    updated_at = NOW()
                WHERE transaction_id = $1       
                """,
                transaction_id
            )

    async def mark_failed(self, transaction_id: str, error: str, next_retry_at: datetime) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET status = 'failed',
                    retry_count = retry_count + 1,
                    error_message = $2,
                    next_retry_at = $3,
                    updated_at = NOW()
                WHERE transaction_id = $1
                """,
                transaction_id, error, next_retry_at
            )

    async def mark_dead_letter(self, transaction_id: str, error: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET status = 'dead_letter',
                    error_message = $2,
                    updated_at = NOW()
                WHERE transaction_id = $1
                """,
                transaction_id, error
            )
    
    async def get_retryable_messages(self, limit: int = 20) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT transaction_id, payload, retry_count
                FROM messages
                WHERE status = 'failed'
                    AND next_retry_at <= NOW()
                ORDER BY next_retry_at ASC
                LIMIT $1
                """,
                limit
            )
            return [dict(row) for row in rows]
        
    async def recover_crashed_messages(
        self, 
        threshold_minutes: int = 5,
        next_retry_delay_seconds: int = 60
    ) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE messages
                SET status = 'failed',
                    next_retry_at = NOW() + $1 * INTERVAL '1 second',
                    updated_at = NOW()
                WHERE status = 'processing'
                AND updated_at < NOW() - $2 * INTERVAL '1 minute'
                """,
                next_retry_delay_seconds,
                threshold_minutes
            )
            # result is like "UPDATE 5" - extract the count
            return int(result.split()[-1])