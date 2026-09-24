from datetime import date, datetime
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str = Field(
        default="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz_example",
        description="Telegram bot token from @BotFather"
    )
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///kvartira.db",
        description="Async SQLite database connection URL"
    )
    TIMEZONE: str = Field(
        default="Asia/Tashkent",
        description="Default timezone for schedules and notifications"
    )
    APARTMENT_NAME: str = Field(
        default="Bizning Kvartira",
        description="Name or description of the apartment"
    )
    ROTATION_BASE_DATE: str = Field(
        default="2026-01-01",
        description="Anchor date (YYYY-MM-DD) for Round-Robin rotation calculations"
    )
    DAILY_FINE_AMOUNT: int = Field(
        default=15000,
        description="Penalty amount in UZS for missed duties"
    )
    GROUP_CHAT_ID: Optional[int] = Field(
        default=None,
        description="Telegram group chat ID to broadcast automated duty reminders"
    )

    @field_validator("GROUP_CHAT_ID", mode="before")
    @classmethod
    def parse_group_chat_id(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return int(v)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def parsed_base_date(self) -> date:
        try:
            return datetime.strptime(self.ROTATION_BASE_DATE, "%Y-%m-%d").date()
        except ValueError:
            return date(2026, 1, 1)


settings = Settings()
