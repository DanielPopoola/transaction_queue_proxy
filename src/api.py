from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from src.metrics import MetricsService
from src.storage import Storage


def create_api(storage: Storage) -> FastAPI:
	app = FastAPI(
		title='Transaction Queue Proxy API',
		description='Metrics and management API for the transaction queue system',
		version='0.1.0',
	)

	metrics_service = MetricsService(storage)

	@app.get('/')
	async def root():
		"""API information and available endpoints"""
		return {
			'service': 'transaction-queue-proxy',
			'version': '0.1.0',
			'endpoints': {
				'metrics': '/metrics',
				'status': '/status',
				'replay': '/replay/{transaction_id}',
				'transactions': '/transactions',
			},
		}

	@app.get('/metrics')
	async def get_metrics():
		return await metrics_service.get_queue_metrics()

	@app.get('/status')
	async def get_status():
		try:
			async with storage.pool.acquire() as conn:
				result = await conn.fetchval('SELECT 1')
				db_healthy = result == 1

			return {
				'status': 'healthy' if db_healthy else 'unhealthy',
				'database': 'connected' if db_healthy else 'disconnected',
				'timestamp': datetime.now(UTC).isoformat(),
			}
		except Exception as e:
			return {
				'status': 'unhealthy',
				'database': 'disconnected',
				'error': str(e),
				'timestamp': datetime.now(UTC).isoformat(),
			}

	@app.post('/replay/{transaction_id}')
	async def replay_transaction(transaction_id: str):
		result = await metrics_service.replay_transaction(transaction_id)
		if not result['success']:
			raise HTTPException(status_code=400, detail=result['error'])

		return result

	@app.get('/transactions')
	async def get_transactions(limit: int = 20):
		if limit < 1:
			raise HTTPException(status_code=400, detail='Limit must be at least 1')

		if limit > 1000:
			raise HTTPException(status_code=400, detail='Limit cannot exceed 1000')

		return await metrics_service.get_recent_transactions(limit)

	return app
