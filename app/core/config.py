from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "MediTouch Backend API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"
    )

settings = Settings()

