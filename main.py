import asyncio
import logging

from background_jobs import send_message
from config.config import load_config
from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from modules import answer, ban, chat, help, id, ignore, keyword, new_msg, ping, restart, start, stop  # noqa: A004
from scheduler import Scheduler
from telethon import TelegramClient
from utils.logger import setup_logger


async def main() -> None:
    """Инициализация и запуск userbot с фоновыми задачами."""
    # Настройка логирования
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("Запуск userbot...")

    # Загрузка конфигурации
    try:
        config = load_config()
    except Exception as e:
        logger.exception(f"Ошибка загрузки конфигурации: {e}")
        return

    # Инициализация клиентов БД
    redis_client = RedisClient(config)
    sqlalchemy_client = SQLAlchemyClient(config)
    try:
        await redis_client.connect()
        await sqlalchemy_client.connect()
        await redis_client.save("work", value=False)
    except Exception as e:
        logger.exception(f"Ошибка при подключении к базам данных: {e}")
        return

    # Инициализация Telegram клиента
    try:
        client = TelegramClient(
            session="userbot",
            api_id=config.api_id,
            api_hash=config.api_hash,
        )
        logger.info("Клиент Telegram инициализирован")
    except Exception as e:
        logger.exception(f"Ошибка при инициализации клиента: {e}")
        return

    # Регистрация модулей
    modules = [
        ping.register,  # Передаем sqlalchemy_client
        id.register,
        restart.register,
        help.register,
        lambda c: start.register(c, redis_client),
        lambda c: stop.register(c, redis_client),
        lambda c: ban.register(c, sqlalchemy_client),
        lambda c: chat.register(c, sqlalchemy_client),
        lambda c: ignore.register(c, sqlalchemy_client),
        lambda c: keyword.register(c, sqlalchemy_client),
        lambda c: answer.register(c, sqlalchemy_client),
        lambda c: new_msg.register(c, sqlalchemy_client),
    ]
    for module in modules:
        try:
            module(client)
        except Exception as e:
            logger.exception(f"Ошибка при регистрации модуля {module.__name__}: {e}")

    # Создание и настройка планировщика
    scheduler = Scheduler()
    # scheduler.every().day.at("10:30").do(send_daily_report, client=client)
    scheduler.every(1).second.do(
        send_message,
        client=client,
        redis_client=redis_client,
        sqlalchemy_client=sqlalchemy_client,
    )
    logger.info("Фоновые задачи запланированы")

    # Функция для выполнения задач в планировщике
    async def run_scheduler() -> None:
        while True:
            await scheduler.run_pending()
            await asyncio.sleep(1)

    # Запуск планировщика и клиента
    try:
        await asyncio.gather(
            client.start(),
            run_scheduler(),  # Фоновые задачи
        )
        logger.info("Userbot успешно запущен")
        await client.run_until_disconnected()
    except Exception as e:
        logger.exception(f"Ошибка при запуске бота: {e}")
    finally:
        await client.disconnect()
        logger.info("Клиент отключен")


if __name__ == "__main__":
    asyncio.run(main())
