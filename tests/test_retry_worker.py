import asyncio
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, patch

from src.retry_worker import RetryWorker


@pytest.mark.asyncio
async def test_retry_worker_processes_retryable_message(storage, processor):
    transaction_id = "TX-RETRY-001"
    payload = {"amount": 1000, "currency": "USD"}
    
    await storage.save_pending(transaction_id, payload)
    await storage.mark_processing(transaction_id)
    
    past_time = datetime.now(tz=UTC) - timedelta(seconds=10)
    await storage.mark_failed(transaction_id, "Temporary error", past_time)
    
    # Mock processor to succeed
    with patch.object(processor, 'process', new_callable=AsyncMock) as mock_process:
        mock_process.return_value = None
        
        # Create worker and run one iteration
        worker = RetryWorker(
            storage=storage,
            processor=processor,
            check_interval=5,
            batch_size=10
        )
        
        worker_task = asyncio.create_task(worker.start())
        await asyncio.sleep(2)
        worker.running = False
        
        try:
            await asyncio.wait_for(worker_task, timeout=2)
        except asyncio.TimeoutError:
            worker_task.cancel()
    
    mock_process.assert_called_once()
    call_args = mock_process.call_args[1]  # Get keyword arguments
    
    assert call_args['transaction_id'] == transaction_id
    assert call_args['payload'] == payload
    assert call_args['retry_count'] == 1 

@pytest.mark.asyncio
async def test_retry_worker_respects_semaphore_limit(storage, processor):
    for i in range(10):
        tx_id = f"TX-CONCURRENT-{i:03d}"
        await storage.save_pending(tx_id, {"amount": i * 100})
        await storage.mark_processing(tx_id)
        past_time = datetime.now(tz=UTC) - timedelta(seconds=10)
        await storage.mark_failed(tx_id, "Error", past_time)
    
    concurrent_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()
    
    async def mock_process(**kwargs):
        nonlocal concurrent_count, max_concurrent
        
        async with lock:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
    
        await asyncio.sleep(0.1)
        
        async with lock:
            concurrent_count -= 1
    
    with patch.object(processor, 'process', new_callable=AsyncMock) as mock_proc:
        mock_proc.side_effect = mock_process
        
        worker = RetryWorker(
            storage=storage,
            processor=processor,
            max_concurrent_retries=3,  # Limit to 3 concurrent
            check_interval=1,
            batch_size=20
        )
        
        worker_task = asyncio.create_task(worker.start())
        await asyncio.sleep(2)
        worker.running = False
        
        try:
            await asyncio.wait_for(worker_task, timeout=3)
        except asyncio.TimeoutError:
            worker_task.cancel()
    
    assert max_concurrent <= 3, f"Expected max 3 concurrent, got {max_concurrent}"

@pytest.mark.asyncio
async def test_retry_worker_continues_after_processing_error(storage, processor):
    for i in range(3):
        tx_id = f"TX-ERROR-{i:03d}"
        await storage.save_pending(tx_id, {"amount": i * 100})
        await storage.mark_processing(tx_id)
        past_time = datetime.now(tz=UTC) - timedelta(seconds=10)
        await storage.mark_failed(tx_id, "Error", past_time)
    
    call_count = 0
    
    async def mock_process(**kwargs):
        nonlocal call_count
        call_count += 1
        
        # Second message fails
        if call_count == 2:
            raise Exception("Simulated processing error")
    
    with patch.object(processor, 'process', new_callable=AsyncMock) as mock_proc:
        mock_proc.side_effect = mock_process
        
        worker = RetryWorker(
            storage=storage,
            processor=processor,
            check_interval=5
        )
        
        worker_task = asyncio.create_task(worker.start())
        await asyncio.sleep(2)
        worker.running = False
        
        try:
            await asyncio.wait_for(worker_task, timeout=2)
        except asyncio.TimeoutError:
            worker_task.cancel()
    
    assert call_count == 3