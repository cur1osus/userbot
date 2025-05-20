import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    """Класс для хранения конфигурации бота."""

    api_id: int
    api_hash: str
    redis_host: str
    redis_port: int
    redis_db: int
    sqlite_path: str

    def __post_init__(self):
        if not all([self.api_id, self.api_hash, self.redis_host, self.sqlite_path]):
            raise ValueError("Все обязательные параметры должны быть заданы в .env файле")


def load_config() -> Config:
    """Загрузка конфигурации из .env файла."""
    logger = logging.getLogger(__name__)
    load_dotenv()

    try:
        api_id = int(os.getenv("API_ID"))
        api_hash = os.getenv("API_HASH")
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_db = int(os.getenv("REDIS_DB", 0))
        sqlite_path = os.getenv("SQLITE_PATH", "sqlite:///userbot.db")
        logger.info("Конфигурация успешно загружена")
        return Config(
            api_id=api_id,
            api_hash=api_hash,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            sqlite_path=sqlite_path,
        )
    except (TypeError, ValueError) as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        raise
