from enum import Enum

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EHRAdapter(Enum):
    GRAPHQL = "graphql"
    PLAYWRIGHT = "playwright"


class ElevenLabsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELEVENLABS_", env_file=".env", extra="ignore")

    api_key: str
    voice_id: str = "SAz9YHcvj6GT2YYXdXww"


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(
        validation_alias=AliasChoices(
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        )
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices(
            "OPENAI_BASE_URL",
            "OPENROUTER_BASE_URL",
        ),
    )
    model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices(
            "OPENROUTER_MODEL",
        ),
    )


class HealthieConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HEALTHIE_", env_file=".env", extra="ignore")

    email: str
    password: str
    base_url: str = "https://secure.gethealthie.com"
    api_url: str = "https://api.gethealthie.com/graphql"
    adapter: EHRAdapter = EHRAdapter.PLAYWRIGHT
    headless: bool = True


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    clinic_timezone: str = "America/New_York"
    elevenlabs: ElevenLabsConfig = Field(default_factory=lambda: ElevenLabsConfig())  # type: ignore[arg-type]
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig())  # type: ignore[arg-type]
    healthie: HealthieConfig = Field(default_factory=lambda: HealthieConfig())  # type: ignore[arg-type]
