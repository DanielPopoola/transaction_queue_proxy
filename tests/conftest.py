import pytest
import asyncpg


from src.processor import Processor
from src.storage import Storage
from src.config import get_settings


@pytest.fixture
async def db_pool():
    config = get_settings()

    pool = await asyncpg.create_pool(
        host=config.postgres_host,
        port=config.postgres_port,
        user=config.postgres_user,
        password=config.postgres_password,
        database=f"{config.postgres_db}_test"
    )

    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE messages")

    yield pool

    await pool.close()


@pytest.fixture
async def storage(db_pool):
    return Storage(db_pool)

@pytest.fixture
async def processor(storage):
    proc = Processor(
        storage=storage,
        downstream_url="http://localhost:8001/process",
        max_retries=3,
        base_delay=60,
        timeout=5.0
    )
    yield proc
    await proc.close()