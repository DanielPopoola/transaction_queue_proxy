import json
import pytest

from datetime import datetime, timedelta, UTC


@pytest.mark.asyncio
async def test_save_pending_creates_transcation(storage):
    transaction_id = "TX-TEST-001"
    payload = {"amount": 10000, "currency": "NGN"}

    await storage.save_pending(transaction_id, payload)

    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE transaction_id = $1",
            transaction_id
        )

    assert row is not None
    assert row['status'] == 'pending'
    assert row['retry_count'] == 0
    assert row['payload'] == json.dumps(payload)


@pytest.mark.asyncio
async def test_save_pending_is_idempotent(storage):
    transaction_id = "TXN-TEST-002"
    payload = {"amount": 15000, "currency": "NGN"}

    await storage.save_pending(transaction_id, payload)
    await storage.save_pending(transaction_id, payload)

    async with storage.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert count == 1

@pytest.mark.asyncio
async def test_mark_processing_updates_status(storage):
    transaction_id = "TX-TEST-003"
    await storage.save_pending(transaction_id, {"amount": 300})
    
    await storage.mark_processing(transaction_id)
    
    async with storage.pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert status == 'processing'

@pytest.mark.asyncio
async def test_mark_success_updates_status(storage):
    transaction_id = "TX-TEST-004"
    await storage.save_pending(transaction_id, {"amount": 400})
    await storage.mark_processing(transaction_id)
    
    await storage.mark_success(transaction_id)
    
    async with storage.pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert status == 'success'

@pytest.mark.asyncio
async def test_mark_failed_increments_retry_count(storage):
    transaction_id = "TX-TEST-005"
    await storage.save_pending(transaction_id, {"amount": 500})
    await storage.mark_processing(transaction_id)

    next_retry = datetime.now(tz=UTC) + timedelta(seconds=60)
    await storage.mark_failed(transaction_id, "Timeout error", next_retry)

    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status, retry_count, error_message, next_retry_at
            FROM messages
            WHERE transaction_id = $1
            """,
            transaction_id
        )

    assert row['status'] == 'failed'
    assert row['retry_count'] == 1
    assert row['error_message'] == "Timeout error"
    

@pytest.mark.asyncio
async def test_mark_failed_increments_on_multiple_failures(storage):
    transaction_id = "TX-TEST-006"
    await storage.save_pending(transaction_id, {"amount": 600})

    for i in range(3):
        await storage.mark_processing(transaction_id)
        next_retry = datetime.now(tz=UTC) + timedelta(seconds=60)
        await storage.mark_failed(transaction_id, f"Error {i+1}", next_retry)

    async with storage.pool.acquire() as conn:
        retry_count = await conn.fetchval(
            "SELECT retry_count FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert retry_count == 3

@pytest.mark.asyncio
async def test_mark_dead_letter(storage):
    transaction_id = "TX-TEST-007"
    await storage.save_pending(transaction_id, {"amount": 700})
    
    await storage.mark_dead_letter(transaction_id, "Max retries exceeded")
    
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error_message FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'dead_letter'
    assert row['error_message'] == "Max retries exceeded"


@pytest.mark.asyncio
async def test_get_retryable_messages_returns_only_ready_failures(storage):
    await storage.save_pending("TX-READY-001", {"amount": 100})
    await storage.mark_processing("TX-READY-001")
    past_time = datetime.now(tz=UTC) - timedelta(seconds=10)
    await storage.mark_failed("TX-READY-001", "Error", past_time)

    await storage.save_pending("TX-FUTURE-001", {"amount": 200})
    await storage.mark_processing("TX-FUTURE-001")
    future_time = datetime.now(tz=UTC) + timedelta(seconds=3600)
    await storage.mark_failed("TX-FUTURE-001", "Error", future_time)
    
    await storage.save_pending("TX-SUCCESS-001", {"amount": 300})
    await storage.mark_processing("TX-SUCCESS-001")
    await storage.mark_success("TX-SUCCESS-001")

    retryable = await storage.get_retryable_messages(limit=10)
    
    assert len(retryable) == 1
    assert retryable[0]['transaction_id'] == "TX-READY-001"

@pytest.mark.asyncio
async def test_get_retryable_messages_respects_limit(storage):
    for i in range(5):
        tx_id = f"TX-LIMIT-{i:03d}"
        await storage.save_pending(tx_id, {"amount": i * 100})
        await storage.mark_processing(tx_id)
        past_time = datetime.now(tz=UTC) - timedelta(seconds=10)
        await storage.mark_failed(tx_id, "Error", past_time)
    
    retryable = await storage.get_retryable_messages(limit=3)
    
    assert len(retryable) == 3

@pytest.mark.asyncio
async def test_recover_crashed_messages(storage):
    transaction_id = "TX-CRASHED-001"
    await storage.save_pending(transaction_id, {"amount": 1000})
    await storage.mark_processing(transaction_id)

    async with storage.pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET updated_at = NOW() - INTERVAL '10 minutes' WHERE transaction_id = $1",
            transaction_id
        )

    recovered_count = await storage.recover_crashed_messages(
        threshold_minutes=5,
        next_retry_delay_seconds=60
    )
    
    assert recovered_count == 1

    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, next_retry_at FROM messages WHERE transaction_id = $1",
            transaction_id
        )
    
    assert row['status'] == 'failed'
    assert row['next_retry_at'] is not None