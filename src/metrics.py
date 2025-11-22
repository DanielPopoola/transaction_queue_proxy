from src.storage import Storage


class MetricsService:
	def __init__(self, storage: Storage):
		self.storage = storage

	async def get_queue_metrics(self) -> dict:
		async with self.storage.pool.acquire() as conn:
			rows = await conn.fetch(
				"""
                SELECT status, COUNT(*) as count
                FROM messages
                GROUP BY status
                """
			)
			metrics = {row['status']: row['count'] for row in rows}
			metrics['total'] = sum(metrics.values())
			for status in ['pending', 'processing', 'success', 'failed', 'dead_letter']:
				if status not in metrics:
					metrics[status] = 0

			return metrics

	async def get_recent_transactions(self, limit: int = 50) -> list[dict]:
		async with self.storage.pool.acquire() as conn:
			rows = await conn.fetch(
				"""
                SELECT transaction_id, status, retry_count, error_message,
                    created_at, updated_at
                FROM messages
                ORDER BY created_at DESC
                LIMIT $1
                """,
				limit,
			)

		transactions = []
		for row in rows:
			transactions.append(
				{
					'transaction_id': row['transaction_id'],
					'status': row['status'],
					'retry_count': row['retry_count'],
					'error_message': row['error_message'],
					'created_at': row['created_at'].isoformat() if row['created_at'] else None,
					'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
				}
			)

		return transactions

	async def replay_transaction(self, transaction_id: str) -> dict:
		async with self.storage.pool.acquire() as conn:
			row = await conn.fetchrow(
				'SELECT status FROM messages WHERE transaction_id = $1', transaction_id
			)
			if row is None:
				return {'success': False, 'error': f'Transaction {transaction_id} not found'}

			if row['status'] != 'dead_letter':
				return {
					'success': False,
					'error': f'Transaction {transaction_id} has status "{row["status"]}", \
                      can only replay dead_letter transactions',
				}

			await conn.execute(
				"""
                UPDATE messages
                SET status = 'pending',
                    retry_count = 0,
                    error_message = NULL,
                    next_retry_at = NULL,
                    updated_at = NOW()
                WHERE transaction_id = $1
                """,
				transaction_id,
			)

			return {
				'success': False,
				'message': f'Transaction {transaction_id} has been reset to \
                      pending and will be retried',
			}
