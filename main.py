import argparse
import asyncio
import logging

from background_jobs import execute_jobs, handling_difference_update_chanel, send_message
from config.config import load_config
from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import Bot
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from scheduler import Scheduler
from sqlalchemy import select
from telethon import TelegramClient  # type: ignore
from utils.logger import setup_logger

# Создаём объект парсера аргументов
parser = argparse.ArgumentParser(description="Запуск Telegram-бота с аргументами")
parser.add_argument("phone", type=str, help="Номер телефона бота")

# Парсим аргументы
args = parser.parse_args()

# Переменная режима
bot_phone = args.phone


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
    except Exception as e:
        logger.exception(f"Ошибка при подключении к базам данных: {e}")
        return

    # Инициализация Telegram клиента
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        bot: Bot = await session.scalar(select(Bot).where(Bot.phone == bot_phone))
        if not bot:
            logger.error(f"Бот {bot_phone} не найден в базе данных")
            return
    try:
        client = TelegramClient(bot.path_session, bot.api_id, bot.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("Сессия не авторизована :(")
            exit()
        else:
            logger.info("Сессия успешно загружена!")
            logger.info("Клиент Telegram инициализирован")
    except Exception as e:
        logger.exception(f"Ошибка при инициализации клиента: {e}")
        exit()
    redis_client.bot_id = f"{bot.api_id}{bot.user_manager_id}"
    await redis_client.save("bot_id", bot.id)
    await redis_client.save("user_manager_id", bot.user_manager_id)

    # Создание и настройка планировщика
    scheduler = Scheduler()
    # scheduler.every().day.at("10:30").do(send_daily_report, client=client)
    scheduler.every(1).second.do(
        send_message,
        client=client,
        redis_client=redis_client,
        sqlalchemy_client=sqlalchemy_client,
    )
    scheduler.every(10).seconds.do(
        handling_difference_update_chanel,
        client=client,
        redis_client=redis_client,
        sqlalchemy_client=sqlalchemy_client,
    )
    scheduler.every(1).seconds.do(
        execute_jobs,
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
