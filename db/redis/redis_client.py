import logging
from typing import Any, TypeAlias

import msgspec
import redis.asyncio as redis
from config.config import Config

Value: TypeAlias = int | str | Any


class RedisClient:
    """Класс для работы с Redis."""

    prefix: str = "userbot"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.redis: redis.Redis | None = None
        self.id_bot = None
        self.logger = logging.getLogger(__name__)
        self.encoder = msgspec.json.Encoder()
        self.decoder = msgspec.json.Decoder()

    async def connect(self) -> None:
        """Подключение к Redis."""
        try:
            self.redis = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
                decode_responses=True,
            )
            await self.redis.ping() if self.redis else None
            self.logger.info("Подключение к Redis установлено")
        except Exception as e:
            self.logger.exception(f"Ошибка подключения к Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Отключение от Redis."""
        if self.redis:
            await self.redis.close()
            self.logger.info("Redis отключен")

    def key(self, key: str | int) -> str:
        return f"{self.prefix}:{self.id_bot}:{key}"

    async def save(self, key: Any, value: Any, ttl: int | None = None) -> None:
        """
        Сохраняет данные в Redis с использованием msgspec для сериализации.

        :param key: Ключ для сохранения данных.
        :param value: Данные для сохранения (словарь).
        :param ttl: Время жизни ключа в секундах (если указано).
        """
        serialized_data = self.encoder.encode(value)
        if not self.redis:
            return
        if ttl:
            await self.redis.setex(self.key(key), ttl, serialized_data)
        else:
            await self.redis.set(self.key(key), serialized_data)

    async def get(self, key: Any) -> Value | None:
        """
        Извлекает данные из Redis и десериализует их с использованием msgspec.

        :param key: Ключ для извлечения данных.
        :return: Десериализованные данные (словарь) или None, если ключ не найден.
        """
        if not self.redis:
            return None
        data = await self.redis.get(self.key(key))
        return self.decoder.decode(data) if data else None

    async def delete(self, key: int | str) -> int | None:
        return await self.redis.delete(self.key(key)) if self.redis else None
