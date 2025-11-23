import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisQueue:
	def __init__(self, redis_url: str = 'redis://localhost:6379'):
		self.redis_url = redis_url
		self.client: redis.Redis | None = None
		self.queue_key = 'transactions:pending'

	async def connect(self):
		self.client = await redis.from_url(self.redis_url, encoding='utf-8', decode_responses=True)
		logger.info(f'Connected to Redis at {self.redis_url}')

	async def close(self):
		if self.client:
			await self.client.close()
			logger.info('Redis connection closed')

	async def enqueue(self, transaction_id: str) -> None:
		await self.client.rpush(self.queue_key, transaction_id)
		logger.debug(f'Enqueued transaction {transaction_id}')

	async def dequeue(self, batch_size: int = 1, timeout: int = 5) -> list[str]:
		if batch_size == 1:
			result = await self.client.blpop(self.queue_key, timeout=timeout)
			if result:
				_, transaction_id = result
				return [transaction_id]
			return []

		pipeline = self.client.pipeline()
		for _ in range(batch_size):
			pipeline.lpop(self.queue_key)
		results = await pipeline.execute()

		return [tx_id for tx_id in results if tx_id is not None]

	async def queue_size(self) -> int:
		return await self.client.llen(self.queue_key)
