import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def measure(operation: str, **context):
	start = time.perf_counter()
	try:
		yield
	finally:
		duration_ms = (time.perf_counter() - start) * 1000
		logger.info(
			f'{operation} completed',
			extra={'operation': operation, 'duration_ms': round(duration_ms, 2), **context},
		)
