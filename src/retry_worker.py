import asyncio
import logging

from src.processor import Processor
from src.storage import Storage

logger = logging.getLogger(__name__)


class RetryWorker:
	def __init__(
		self,
		storage: Storage,
		processor: Processor,
		max_concurrent_retries: int = 5,
		check_interval: int = 10,
		batch_size: int = 20,
	):
		self.storage = storage
		self.processor = processor
		self.check_interval = check_interval
		self.batch_size = batch_size
		self.semaphore = asyncio.Semaphore(max_concurrent_retries)
		self.running = False

	async def start(self):
		logger.info('Retry worker starting...')
		self.running = True

		while self.running:
			try:
				messages = await self.storage.get_retryable_messages(self.batch_size)
				if messages:
					logger.info(f'Found {len(messages)} messages to retry')
					tasks = [self._retry_message(message) for message in messages]
					await asyncio.gather(*tasks, return_exceptions=True)

				await asyncio.sleep(self.check_interval)
			except Exception as e:
				logger.error(f'Error in retry worker loop: {e}')
				continue

	async def _retry_message(self, message: dict):
		async with self.semaphore:
			try:
				await self.processor.process(**message)
			except Exception as e:
				logger.error(f'Unexpected error occured: {e}')

	async def stop(self):
		logger.info('Stopping retry worker...')
		self.running = False
