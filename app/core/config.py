from typing import List, Union, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "MediTouch Backend API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "t", "yes", "y", "debug")
        return bool(v)

    # MongoDB Settings
    MONGODB_URL: str = Field(default="mongodb://localhost:27017")
    MONGODB_DB_NAME: str = Field(default="meditouch")

    # Security & JWT
    JWT_SECRET_KEY: str = Field(default="meditouch_dev_super_secret_jwt_key_change_in_production_32bytes_min")
    JWT_REFRESH_SECRET_KEY: str = Field(default="meditouch_dev_super_secret_refresh_jwt_key_change_in_production_32bytes_min")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000", "http://localhost:8000", "*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # bKash Gateway
    BKASH_APP_KEY: str = Field(default="sandbox_app_key")
    BKASH_APP_SECRET: str = Field(default="sandbox_app_secret")
    BKASH_USERNAME: str = Field(default="sandbox_username")
    BKASH_PASSWORD: str = Field(default="sandbox_password")
    BKASH_BASE_URL: str = Field(default="https://tokenized.sandbox.bka.sh/v1.2.0-beta")
    BKASH_CALLBACK_URL: str = Field(default="http://localhost:8000/api/v1/payments/bkash/callback")
    BKASH_SANDBOX_MODE: bool = True

    # ZEGOCLOUD
    ZEGOCLOUD_APP_ID: int = Field(default=123456789)
    ZEGOCLOUD_SERVER_SECRET: str = Field(default="0123456789abcdef0123456789abcdef")
    ZEGOCLOUD_TOKEN_EXPIRY_SECONDS: int = 3600

    # Cloudinary CDN & Storage
    CLOUDINARY_CLOUD_NAME: str = Field(default="")
    CLOUDINARY_API_KEY: str = Field(default="")
    CLOUDINARY_API_SECRET: str = Field(default="")
    CLOUDINARY_SECURE: bool = True

    # Business Logic Constants
    PLATFORM_FEE_PERCENTAGE: float = 10.0
    PLATFORM_DELIVERY_FEE_BDT: float = 60.0
    APPOINTMENT_JOINABLE_WINDOW_BEFORE_MINUTES: int = 5
    APPOINTMENT_JOINABLE_WINDOW_AFTER_MINUTES: int = 30

    # SMTP Email Configuration
    SMTP_HOST: str = Field(default="smtp.gmail.com")
    SMTP_PORT: int = Field(default=465)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_EMAIL: str = Field(default="noreply@meditouch.com")
    SMTP_FROM_NAME: str = Field(default="MediTouch Telemedicine")
    SMTP_TLS: bool = True
    SMTP_SSL: bool = True
    FRONTEND_BASE_URL: str = Field(default="http://localhost:3000")

    # Multi-Provider LLM Configuration
    # 1. Groq (Sequential Multi-Model Fallback Chain)
    GROQ_API_KEY: str = Field(default="")
    GROQ_BASE_URL: str = Field(default="https://api.groq.com/openai/v1")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile")
    GROQ_MODELS: str = Field(default="llama-3.3-70b-versatile,openai/gpt-oss-120b,qwen/qwen3.8-27b,qwen/qwen3.6-27b,openai/gpt-oss-20b,groq/compound,groq/compound-mini,allam-2-7b")

    # 2. OpenRouter (Multi-Model Free/Commercial Chain)
    OPENROUTER_API_KEY: str = Field(default="")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")
    OPENROUTER_MODEL: str = Field(default="meta-llama/llama-3.3-70b-instruct:free")
    OPENROUTER_MODELS: str = Field(default="meta-llama/llama-3.3-70b-instruct:free,google/gemini-2.0-flash-exp:free,qwen/qwen-2.5-72b-instruct:free")

    # 3. TokenRouter
    TOKENROUTER_API_KEY: str = Field(default="")
    TOKENROUTER_BASE_URL: str = Field(default="https://api.tokenrouter.com/v1")
    TOKENROUTER_MODEL: str = Field(default="z-ai/glm-5.3-free")
    TOKENROUTER_MODELS: str = Field(default="z-ai/glm-5.3-free")

    # Provider fallback priority order (comma-separated: groq,openrouter,tokenrouter)
    LLM_PROVIDER_ORDER: str = Field(default="groq,openrouter,tokenrouter")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"
    )

settings = Settings()

