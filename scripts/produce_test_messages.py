import asyncio
import json

from aiokafka import AIOKafkaProducer


async def produce_test_messages():
	producer = AIOKafkaProducer(
		bootstrap_servers='localhost:29092',
		value_serializer=lambda v: json.dumps(v).encode('utf-8'),
	)

	await producer.start()

	try:
		for i in range(5):
			transaction = {
				'transaction_id': f'TX-TEST-{i:03d}',
				'amount': (i + 1) * 100,
				'currency': 'USD',
				'user_id': f'user-{i}',
			}

			await producer.send('transactions.incoming', value=transaction)
			print(f'Sent: {transaction["transaction_id"]}')

		print('All messages sent!')

	finally:
		await producer.stop()


if __name__ == '__main__':
	asyncio.run(produce_test_messages())
