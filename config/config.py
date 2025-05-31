import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    """Класс для хранения конфигурации бота."""

    redis_host: str
    redis_port: int
    redis_db: int
    mysql_path: str


def load_config() -> Config:
    """Загрузка конфигурации из .env файла."""
    logger = logging.getLogger(__name__)
    load_dotenv()

    try:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_db = int(os.getenv("REDIS_DB", 0))
        mysql_path = os.getenv("MYSQL_PATH")
        logger.info("Конфигурация успешно загружена")
        return Config(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            mysql_path=mysql_path,
        )
    except (TypeError, ValueError) as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        raise
