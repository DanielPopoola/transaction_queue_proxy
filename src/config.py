from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
	postgres_user: str = Field(..., min_length=1)
	postgres_password: str = Field(..., min_length=1)
	postgres_db: str = Field(..., min_length=1)
	postgres_host: str = 'localhost'
	postgres_port: int = Field(5432, ge=1, le=65535)

	downstream_url: str = 'http://localhost:8001/process'

	kafka_broker: str = Field('localhost:9092', min_length=1)

	max_retries: int = Field(5, ge=1)
	base_delay: int = Field(60, ge=0)
	max_delay: int = Field(3600, ge=1)

	max_concurrent_retries: int = Field(5, ge=1, le=50)

	@field_validator('kafka_broker')
	@classmethod
	def validate_kafka_broker(cls, v):
		if ':' not in v:
			raise ValueError("kafka_broker must include a port, e.g., 'localhost:9092'")
		return v

	@model_validator(mode='after')
	def validate_delays(self):
		if self.max_delay < self.base_delay:
			raise ValueError('max_delay must be greater than or equal base_delay')
		return self

	@property
	def database_url(self) -> str:
		return (
			f'postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}'
			f'@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}'
		)

	model_config = SettingsConfigDict(env_file='.env', case_sensitive=False, extra='ignore')


@lru_cache
def get_settings() -> Config:
	return Config()
