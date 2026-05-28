from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — must be asyncpg driver for async SQLAlchemy
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/gusto_pos"
    DB_ECHO: bool = False

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
