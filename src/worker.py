import asyncio
import json
import logging

from src.instrumentation import measure
from src.processor import Processor
from src.queue import RedisQueue
from src.storage import Storage

logger = logging.getLogger(__name__)


class Worker:
	def __init__(
		self,
		worker_id: str,
		storage: Storage,
		processor: Processor,
		queue: RedisQueue,
		batch_size: int = 1,
	):
		self.worker_id = worker_id
		self.storage = storage
		self.processor = processor
		self.queue = queue
		self.batch_size = batch_size
		self.running = False

	async def start(self):
		logger.info(f'Worker {self.worker_id} starting...')
		self.running = True

		while self.running:
			try:
				transaction_ids = await self.queue.dequeue(batch_size=self.batch_size, timeout=5)

				if not transaction_ids:
					continue

				for tx_id in transaction_ids:
					await self._process_transaction(tx_id)

			except Exception as e:
				logger.error(f'Worker {self.worker_id} error: {e}')
				await asyncio.sleep(1)

	async def stop(self):
		logger.info(f'Worker {self.worker_id} stopping...')
		self.running = False

	async def _process_transaction(self, transaction_id: str):
		try:
			async with measure(
				'worker_fetch_from_db', transaction_id=transaction_id, worker_id=self.worker_id
			):
				async with self.storage.pool.acquire() as conn:
					row = await conn.fetchrow(
						"""
                        SELECT payload, retry_count
                        FROM messages
                        WHERE transaction_id = $1
                        """,
						transaction_id,
					)

				if not row:
					logger.error(
						f'Transaction {transaction_id} not found in database'
						f'(worker {self.worker_id})'
					)
					return

				payload = json.loads(row['payload'])
				retry_count = row['retry_count']

				logger.info(
					f'Worker {self.worker_id} processing {transaction_id} '
					f'(retry_count={retry_count})'
				)

				async with measure(
					'worker_process_transaction',
					transaction_id=transaction_id,
					worker_id=self.worker_id,
				):
					await self.processor.process(
						transaction_id=transaction_id, payload=payload, retry_count=retry_count
					)

		except Exception as e:
			logger.error(f'Worker {self.worker_id} failed to process {transaction_id}: {e}')
