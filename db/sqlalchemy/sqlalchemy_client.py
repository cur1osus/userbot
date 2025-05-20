import logging

from config.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


class SQLAlchemyClient:
    """Класс для асинхронной работы с SQLite через SQLAlchemy и aiosqlite."""

    def __init__(self, config: Config):
        self.config = config
        self.engine = None
        self.session_factory = None
        self.logger = logging.getLogger(__name__)

    async def connect(self):
        """Подключение к SQLite и создание таблиц."""
        try:
            self.engine = create_async_engine(self.config.sqlite_path, echo=False)
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self.session_factory = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
            self.logger.info("Подключение к SQLite установлено")
        except Exception as e:
            self.logger.error(f"Ошибка подключения к SQLite: {e}")
            raise

    async def disconnect(self):
        """Отключение от SQLite."""
        if self.engine:
            await self.engine.dispose()
            self.logger.info("SQLite отключен")


