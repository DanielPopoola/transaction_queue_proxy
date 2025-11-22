import logging

import httpx

from src.backoff import calculate_next_retry
from src.storage import Storage

logger = logging.getLogger(__name__)


class Processor:
	def __init__(
		self,
		storage: Storage,
		downstream_url: str,
		max_retries: int = 5,
		base_delay: int = 60,
		max_delay: int = 3600,
		timeout: float = 30.0,
	):
		self.storage = storage
		self.downstream_url = downstream_url
		self.max_retries = max_retries
		self.base_delay = base_delay
		self.max_delay = max_delay
		self.timeout = timeout
		self.client = httpx.AsyncClient(timeout=timeout)

	async def close(self):
		"""Close the HTTP client (call on shutdown)"""
		await self.client.aclose()

	async def process(self, transaction_id: str, payload: dict, retry_count: int = 0):
		logger.info(f'Processing transaction {transaction_id}, attempt {retry_count + 1}')

		await self.storage.mark_processing(transaction_id)

		try:
			response = await self.client.post(
				self.downstream_url, json={'transaction_id': transaction_id, **payload}
			)

			if 200 <= response.status_code < 300:
				await self.storage.mark_success(transaction_id)
				logger.info(f'Transaction {transaction_id} succeeded')
				return

			await self._handle_error(
				transaction_id=transaction_id,
				status_code=response.status_code,
				error_message=f'Downstream returned {response.status_code}: {response.text}',
				retry_count=retry_count,
			)

		except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
			logger.warning(f'Transaction {transaction_id} failed with network error: {e}')
			await self._handle_error(
				transaction_id=transaction_id,
				status_code=None,
				error_message=f'Network error: {type(e).__name__}',
				retry_count=retry_count,
			)

		except Exception as e:
			logger.error(f'Transaction {transaction_id} failed with unexpected error: {e}')
			await self.storage.mark_dead_letter(
				transaction_id=transaction_id, error=f'Unexpected error: {str(e)}'
			)

	async def _handle_error(
		self, transaction_id: str, status_code: int | None, error_message: str, retry_count: int
	):
		is_transient = self._is_transient_error(status_code)

		if not is_transient:
			logger.error(f'Transaction {transaction_id} dead lettered: {error_message}')
			await self.storage.mark_dead_letter(transaction_id=transaction_id, error=error_message)
			return

		if retry_count >= self.max_retries:
			logger.error(f'Transaction {transaction_id} exhausted retries: {error_message}')
			await self.storage.mark_dead_letter(
				transaction_id=transaction_id,
				error=f'Max retries exceeded. Last error: {error_message}',
			)
			return

		next_retry_at = calculate_next_retry(
			retry_count=retry_count, base_delay=self.base_delay, max_delay=self.max_delay
		)

		logger.warning(
			f'Transaction {transaction_id} will retry at {next_retry_at}. '
			f'Retry count: {retry_count + 1}/{self.max_retries}'
		)

		await self.storage.mark_failed(
			transaction_id=transaction_id, error=error_message, next_retry_at=next_retry_at
		)

	def _is_transient_error(self, status_code: int | None) -> bool:
		if status_code is None:
			return True

		if 500 <= status_code < 600:
			return True

		return status_code == 429
