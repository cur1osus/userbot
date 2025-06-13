import logging

from config.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base  # noqa: F401


class SQLAlchemyClient:
    """Класс для асинхронной работы с mysql через SQLAlchemy и aiomysql."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.engine = None
        self.session_factory = None
        self.logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        """Подключение к mysql и создание таблиц."""
        try:
            self.engine = create_async_engine(
                self.config.mysql_path,
                pool_pre_ping=True,
                pool_recycle=900,
            )
            self.session_factory = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
            self.logger.info("Подключение к mysql установлено")
        except Exception as e:
            self.logger.exception(f"Ошибка подключения к mysql: {e}")
            raise

    async def disconnect(self) -> None:
        """Отключение от mysql."""
        if self.engine:
            await self.engine.dispose()
            self.logger.info("mysql отключен")
