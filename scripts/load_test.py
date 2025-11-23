import argparse
import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from aiokafka import AIOKafkaProducer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def run_load_test(rate: int, duration: int, topic: str):
	producer = AIOKafkaProducer(
		bootstrap_servers='localhost:29092',
		value_serializer=lambda v: json.dumps(v).encode('utf-8'),
	)

	try:
		await producer.start()
		logger.info('Producer started...')

		total_expected_messages = rate * duration
		logger.info(f'Starting load test: {rate} msg/sec for {duration} seconds.')
		logger.info(f'Target total: {total_expected_messages} messages.')

		start_time = time.monotonic()
		messages_sent = 0

		for i in range(total_expected_messages):
			payload = {
				'transaction_id': f'LOAD-TEST-{uuid.uuid4().hex[:8]}-{i:05d}',
				'user_id': f'user_{i % 100}',  # Simulate 100 different users
				'amount': round(10.0 + (i % 50), 2),
				'currency': 'USD',
				'timestamp': datetime.now(tz=UTC).isoformat(),
				'source': 'load_test',
			}

			await producer.send(topic, payload)
			messages_sent += 1

			elapsed_time = time.monotonic() - start_time
			target_time = messages_sent / rate
			sleep_time = target_time - elapsed_time

			if sleep_time > 0:
				await asyncio.sleep(sleep_time)

			if messages_sent % rate == 0:
				print(
					f'\rStatus: Sent {messages_sent}/{total_expected_messages} '
					f'({(messages_sent / total_expected_messages) * 100:.1f}%)',
					end='',
					flush=True,
				)

		total_time = time.monotonic() - start_time
		print()

		logger.info('Flushing remaining messages...')
		await producer.flush()

		actual_rate = messages_sent / total_time
		logger.info('-' * 40)
		logger.info('Load Test Complete.')
		logger.info(f'Total Sent:  {messages_sent}')
		logger.info(f'Total Time:  {total_time:.2f}s')
		logger.info(f'Actual Rate: {actual_rate:.2f} msg/sec')
		logger.info('-' * 40)

	except KeyboardInterrupt:
		logger.warning('\nLoad test stopped manually.')
	except Exception as e:
		logger.error(f'An error occurred: {e}')
	finally:
		await producer.stop()
		logger.info('Producer closed.')


def main():
	parser = argparse.ArgumentParser(description='Kafka Load Generator')

	parser.add_argument('--rate', type=int, default=10, help='Messages per second (default: 10)')

	parser.add_argument(
		'--duration', type=int, default=10, help='Duration in seconds (default: 10)'
	)

	parser.add_argument(
		'--topic', type=str, default='transactions.incoming', help='Kafka topic to publish to'
	)

	args = parser.parse_args()

	with suppress(KeyboardInterrupt):
		asyncio.run(run_load_test(args.rate, args.duration, args.topic))


if __name__ == '__main__':
	main()
