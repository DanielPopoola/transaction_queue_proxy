import json
import logging

from aiokafka import AIOKafkaConsumer

from src.processor import Processor
from src.storage import Storage

logger = logging.getLogger(__name__)


class Consumer:
    def __init__(
            self,
            storage: Storage,
            processor: Processor,
            kafka_broker: str,
            topic: str,
            group_id: str = "transaction-processor-group"
    ):
        self.storage = storage
        self.processor = processor
        self.kafka_broker = kafka_broker
        self.topic = topic
        self.group_id = group_id
        self.consumer = None
        self.running = False

    async def start(self):
        logger.info(f"Starting consumer for topic {self.topic}")

        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.kafka_broker,
            group_id=self.group_id,
            auto_offset_reset='earliest',
            enable_auto_commit=False,
            consumer_timeout_ms=1000,
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        await self.consumer.start()
        self.running = True
        logger.info("Consumer started successfully")

    async def stop(self):
        logger.info("Stopping consumer...")
        self.running = False
        
        if self.consumer:
            await self.consumer.stop()
        
        logger.info("Consumer stopped")

    async def consume(self):
        if not self.consumer:
            raise RuntimeError("Consumer not started. Call start() first.")
        
        logger.info("Beginning message consumption")

        try:
            while self.running:
                data = await self.consumer.getmany(timeout_ms=1000, max_records=10)
                
                if not data:
                    continue
            
                for _, messages in data.items():
                    for message in messages:
                        if not self.running:
                            logger.info("Stop signal received, finishing current batch")
                            return
                        
                        await self._process_message(message)
                        await self.consumer.commit()
                        
        except Exception as e:
            logger.error(f"Error during consumption: {e}")
            raise
        finally:
            logger.info("Consumer loop exiting")

    async def _process_message(self, message):
        try:
            transaction_id = message.value.get('transaction_id')
            payload = message.value
            
            if not transaction_id:
                logger.error(f"Message missing transaction_id: {message.value}")
                # Commit anyway to skip bad messages
                await self.consumer.commit()
                return
            
            logger.info(f"Received transaction {transaction_id} from Kafka")

            await self.storage.save_pending(transaction_id, payload)

            await self.processor.process(
                transaction_id=transaction_id,
                payload=payload,
                retry_count=0
            )
            await self.consumer.commit()
            logger.info(f"Committed offset for transaction {transaction_id}")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            # Don't commit - Kafka will redeliver on restart
            raise