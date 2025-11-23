import asyncio
import logging
import signal
import sys

import asyncpg
import uvicorn
from aiokafka.errors import KafkaConnectionError
from pythonjsonlogger import json as json_logger

from src.api import create_api
from src.config import get_settings
from src.consumer import Consumer
from src.processor import Processor
from src.retry_worker import RetryWorker
from src.storage import Storage

handler = logging.StreamHandler(sys.stdout)
formatter = json_logger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
handler.setFormatter(formatter)

logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)


class Application:
	def __init__(self):
		self.config = get_settings()
		self.pool = None
		self.storage = None
		self.processor = None
		self.consumer = None
		self.retry_worker = None
		self.queue = None
		self.workers = []
		self.api_app = None
		self.api_server = None
		self.shutdown_event = asyncio.Event()

	async def startup(self):
		logger.info('Starting application...')

		self.pool = await asyncpg.create_pool(
			host=self.config.postgres_host,
			port=self.config.postgres_port,
			user=self.config.postgres_user,
			password=self.config.postgres_password,
			database=self.config.postgres_db,
			min_size=5,
			max_size=20,
		)
		logger.info('Database pool created')

		self.storage = Storage(self.pool)

		self.api_app = create_api(self.storage)

		config = uvicorn.Config(self.api_app, host='0.0.0.0', port=8000, log_level='info')
		self.api_server = uvicorn.Server(config)
		logger.info('API server configured on port 8000')

		self.processor = Processor(
			storage=self.storage,
			downstream_url=self.config.downstream_url,
			max_retries=self.config.max_retries,
			base_delay=self.config.base_delay,
			max_delay=self.config.max_delay,
		)

		from src.queue import RedisQueue

		self.queue = RedisQueue(redis_url=self.config.redis_url)
		await self.queue.connect()
		logger.info('Redis queue connected')

		self.consumer = Consumer(
			storage=self.storage,
			processor=self.processor,
			kafka_broker=self.config.kafka_broker,
			topic='transactions.incoming',
			queue=self.queue,
		)

		self.retry_worker = RetryWorker(
			storage=self.storage,
			processor=self.processor,
			max_concurrent_retries=self.config.max_concurrent_retries,
			check_interval=10,
			batch_size=20,
		)

		recovered = await self.storage.recover_crashed_messages()
		if recovered > 0:
			logger.warning(f'Recovered {recovered} crashed messages')

		from src.worker import Worker

		num_workers = 5
		for i in range(num_workers):
			worker = Worker(
				worker_id=f'worker-{i}',
				storage=self.storage,
				processor=self.processor,
				queue=self.queue,
				batch_size=1,
			)
			self.workers.append(worker)
		logger.info(f'Created {num_workers} workers')

		max_retries = 10
		for attempt in range(max_retries):
			try:
				logger.info(f'Connecting to Kafka (Attempt {attempt + 1}/{max_retries})...')
				await self.consumer.start()
				logger.info('Connected to Kafka successfully.')
				break
			except KafkaConnectionError:
				if attempt == max_retries - 1:
					logger.error('Max retries reached. Could not connect to Kafka.')
					raise
				logger.warning('Kafka not ready yet. Retrying in 5 seconds...')
				await asyncio.sleep(5)
			except Exception as e:
				if attempt == max_retries - 1:
					raise
				logger.warning(f'Connection failed: {e}. Retrying in 5 seconds...')
				await asyncio.sleep(5)

		logger.info('Application started successfully')

	async def shutdown(self):
		logger.info('Shutting down application...')

		if self.consumer:
			await self.consumer.stop()

		if self.workers:
			for worker in self.workers:
				await worker.stop()
			logger.info('All workers stopped')

		if self.retry_worker:
			await self.retry_worker.stop()

		if self.queue:
			await self.queue.close()

		if self.processor:
			await self.processor.close()

		if self.pool:
			await self.pool.close()

		if self.api_server:
			self.api_server.should_exit = True
			logger.info('API server shutdown initiated')

		logger.info('Application shutdown complete')

	async def run(self):
		await self.startup()

		loop = asyncio.get_event_loop()
		for sig in (signal.SIGTERM, signal.SIGINT):
			loop.add_signal_handler(sig, lambda: asyncio.create_task(self._handle_shutdown()))

		try:
			consumer_task = asyncio.create_task(self.consumer.consume(), name='kafka-consumer')
			retry_task = asyncio.create_task(self.retry_worker.start(), name='retry-worker')
			api_task = asyncio.create_task(self.api_server.serve(), name='api-server')

			worker_tasks = [
				asyncio.create_task(worker.start(), name=f'worker-{i}')
				for i, worker in enumerate(self.workers)
			]

			await asyncio.gather(consumer_task, retry_task, api_task, *worker_tasks)

		except Exception as e:
			logger.error(f'Error in main loop: {e}')
		finally:
			await self.shutdown()

	async def _handle_shutdown(self):
		logger.info('Shutdown signal received')
		self.shutdown_event.set()
		if self.consumer:
			self.consumer.running = False

		for worker in self.workers:
			worker.running = False

		if self.retry_worker:
			self.retry_worker.running = False


async def main():
	app = Application()
	await app.run()


if __name__ == '__main__':
	asyncio.run(main())
