import asyncio
import logging
import signal

import asyncpg

from src.config import get_settings
from src.consumer import Consumer
from src.processor import Processor
from src.retry_worker import RetryWorker
from src.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Application:
    def __init__(self):
        self.config = get_settings()
        self.pool = None
        self.storage = None
        self.processor = None
        self.consumer = None
        self.retry_worker = None
        self.shutdown_event = asyncio.Event()

    async def startup(self):
        logger.info("Starting application...")

        self.pool = await asyncpg.create_pool(
            host=self.config.postgres_host,
            port=self.config.postgres_port,
            user=self.config.postgres_user,
            password=self.config.postgres_password,
            database=self.config.postgres_db,
            min_size=5,
            max_size=20
        )
        logger.info("Database pool created")
        
        self.storage = Storage(self.pool)

        self.processor = Processor(
            storage=self.storage,
            downstream_url="http://localhost:8001/process",
            max_retries=self.config.max_retries,
            base_delay=self.config.base_delay,
            max_delay=self.config.max_delay
        )

        self.consumer = Consumer(
            storage=self.storage,
            processor=self.processor,
            kafka_broker=self.config.kafka_broker,
            topic="transactions.incoming"
        )

        self.retry_worker = RetryWorker(
            storage=self.storage,
            processor=self.processor,
            max_concurrent_retries=self.config.max_concurrent_retries,
            check_interval=10,
            batch_size=20
        )

        recovered = await self.storage.recover_crashed_messages()
        if recovered > 0:
            logger.warning(f"Recovered {recovered} crashed messages")
        
        await self.consumer.start()
        logger.info("Application started successfully")

    async def shutdown(self):
        logger.info("Shutting down application...")
        
        if self.consumer:
            await self.consumer.stop()
        
        if self.retry_worker:
            await self.retry_worker.stop()
        
        if self.processor:
            await self.processor.close()
        
        if self.pool:
            await self.pool.close()
        
        logger.info("Application shutdown complete")

    async def run(self):
        await self.startup()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._handle_shutdown())
            )

        try:
            consumer_task = asyncio.create_task(
                self.consumer.consume(),
                name="kafka-consumer"
            )
            retry_task = asyncio.create_task(
                self.retry_worker.start(),
                name="retry-worker"
            )
            
            await asyncio.gather(consumer_task, retry_task)
            
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            await self.shutdown()

    async def _handle_shutdown(self):
        logger.info("Shutdown signal received")
        self.shutdown_event.set()
        if self.consumer:
            self.consumer.running = False
        if self.retry_worker:
            self.retry_worker.running = False


async def main():
    app = Application()
    await app.run()


if __name__ == '__main__':
    asyncio.run(main())