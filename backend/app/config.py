from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SRE Agent"
    app_version: str = "0.1.0"
    database_url: str = (
        "postgresql://opsswarm:opsswarm@localhost:5432/opsswarm"
    )
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e4b"
    demo_service_url: str = "http://127.0.0.1:8100"
    analysis_timeout_seconds: float = Field(default=60, gt=0, le=300)
    mcp_execution_timeout_seconds: float = Field(default=20, gt=0, le=120)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
