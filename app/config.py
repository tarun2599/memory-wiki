from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://memorywiki:memorywiki@localhost:5432/memorywiki"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "memories"
    s3_region: str = "us-east-1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_provider: str = "mock"
    log_level: str = "INFO"
    memory_prefix: str = "wiki/"
    celery_max_retries: int = 3
    celery_retry_backoff: int = 30


settings = Settings()
