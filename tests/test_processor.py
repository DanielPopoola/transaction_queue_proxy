import pytest
import httpx
from unittest.mock import AsyncMock, patch
from datetime import datetime, UTC


@pytest.mark.asyncio
async def test_process_success(processor, storage):
    transaction_id = "TX-SUCCES-001"
    payload = {"amount": 100, "currency": "NGN"}

    await storage.save_pending(transaction_id, payload)
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "OK"

    with patch.object(processor.client, 'post', return_value=mock_response):
        await processor.process(transaction_id, payload, retry_count=0)

    async with storage.pool.acquire() as conn:
        status = await conn.fetchval(
            """SELECT status FROM messages WHERE transaction_id = $1""",
            transaction_id
        )

    assert status == 'success'

@pytest.mark.asyncio
async def test_process_transient_error_schedules_retry(processor, storage):
    transaction_id = "TX-RETRY-001"
    payload = {"amount": 200, "currency": "NGN"}

    await storage.save_pending(transaction_id, payload)
    mock_response = AsyncMock()
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"

    with patch.object(processor.client, 'post', return_value=mock_response):
        await processor.process(transaction_id, payload, retry_count=0)

    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, retry_count, next_retry_at FROM messages WHERE transaction_id = $1",
            transaction_id
        )

    assert row['status'] == 'failed'
    assert row['retry_count'] == 1
    assert row['next_retry_at'] is not None
    assert row['next_retry_at'] > datetime.now(tz=UTC)

@pytest.mark.asyncio
async def test_process_max_retries_dead_letters(processor, storage):
    transaction_id = "TX-MAXRETRY-001"
    payload = {"amount": 300, "currency": "NGN"}
    
    await storage.save_pending(transaction_id, payload)
    mock_response = AsyncMock()
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"

    with patch.object(processor.client, 'post', return_value=mock_response):
        await processor.process(transaction_id, payload, retry_count=3)

    async with storage.pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM messages WHERE transaction_id = $1",
            transaction_id
        )

    assert status == 'dead_letter'

@pytest.mark.asyncio
async def test_process_permanent_error_immediate_dead_letter(processor, storage):
    transaction_id = "TX-BADREQ-001"
    payload = {"amount": 400, "currency": "NGN"}
    
    await storage.save_pending(transaction_id, payload)
    mock_response = AsyncMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    
    with patch.object(processor.client, 'post', return_value=mock_response):
        await processor.process(transaction_id, payload, retry_count=0)
    
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, retry_count FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'dead_letter'
    assert row['retry_count'] == 0  # Never incremented

@pytest.mark.asyncio
async def test_process_rate_limit_schedules_retry(processor, storage):
    transaction_id = "TX-RATELIMIT-001"
    payload = {"amount": 500, "currency": "NGN"}
    
    await storage.save_pending(transaction_id, payload)
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"

    with patch.object(processor.client, 'post', return_value=mock_response):
        await processor.process(transaction_id, payload, retry_count=0)
    
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, retry_count FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'failed'
    assert row['retry_count'] == 1

@pytest.mark.asyncio
async def test_process_network_timeout_schedules_retry(processor, storage):
    transaction_id = "TX-TIMEOUT-001"
    payload = {"amount": 600, "currency": "NGN"}
    
    await storage.save_pending(transaction_id, payload)
    
    with patch.object(processor.client, 'post', side_effect=httpx.TimeoutException("Timeout")):
        await processor.process(transaction_id, payload, retry_count=0)
    
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error_message FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'failed'
    assert 'Network error' in row['error_message']

@pytest.mark.asyncio
async def test_process_unexpected_exception_dead_letters(processor, storage):
    transaction_id = "TX-UNEXPECTED-001"
    payload = {"amount": 700, "currency": "NGN"}
    
    await storage.save_pending(transaction_id, payload)

    with patch.object(processor.client, 'post', side_effect=ValueError("Unexpected error")):
        await processor.process(transaction_id, payload, retry_count=0)
    
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error_message FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'dead_letter'
    assert 'Unexpected error' in row['error_message']
