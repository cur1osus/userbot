import argparse
import asyncio
import datetime
import logging
import os
import stat
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.background_tasks import execute_jobs, handling_difference_update_chanel, send_message, update_bot_name
from bot.db.base import create_db_session_pool
from bot.db.func import RedisStorage
from bot.db.models import Bot as UserBot
from bot.scheduler import Scheduler
from bot.settings import se
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio.session import AsyncSession
from telethon import TelegramClient

# Создаём объект парсера аргументов
parser = argparse.ArgumentParser(description="Запуск Telegram-бота с аргументами")
parser.add_argument("path_session", type=str, help="Путь к сессии")
parser.add_argument("api_id", type=int, help="ID бота")
parser.add_argument("api_hash", type=str, help="Хэш бота")

# Парсим аргументы
args = parser.parse_args()
bot_path_session: str = args.path_session
bot_api_id: int = int(args.api_id)
bot_api_hash: str = args.api_hash

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _moscow_time_converter(timestamp: float) -> time.struct_time:
    return datetime.datetime.fromtimestamp(timestamp, tz=MOSCOW_TZ).timetuple()


def ensure_session_writable(session_path: str) -> str | None:
    """Validate session path/directory and try to make it writable."""
    path = Path(session_path).expanduser()
    session_dir = path.parent

    try:
        session_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Не удалось создать папку для сессии %s: %s", session_dir, exc)
        return None

    if not os.access(session_dir, os.W_OK):
        try:
            session_dir.chmod(session_dir.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        except OSError as exc:
            logger.error("Нет прав на запись в каталог сессии %s: %s", session_dir, exc)
            return None

    try:
        if not path.exists():
            path.touch(mode=0o600, exist_ok=True)
        else:
            mode = path.stat().st_mode
            if not mode & stat.S_IWUSR:
                path.chmod(mode | stat.S_IWUSR)
    except OSError as exc:
        logger.error("Не удалось подготовить файл сессии %s: %s", path, exc)
        return None

    try:
        test_file = session_dir / f".{path.name}.write-test"
        with open(test_file, "wb") as fh:
            fh.write(b"ok")
        test_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            "Каталог %s недоступен для записи (для SQLite журнала): %s",
            session_dir,
            exc,
        )
        return None

    if not os.access(path, os.W_OK):
        logger.error("Файл сессии %s доступен только для чтения", path)
        return None

    return str(path)


scheduler = Scheduler()


async def run_scheduler() -> None:
    while True:
        await scheduler.run_pending()
        await asyncio.sleep(1)


async def set_tasks(
    client: TelegramClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
):
    scheduler.every(1).seconds.do(
        handling_difference_update_chanel,
        client,
        sessionmaker,
        storage,
    )
    scheduler.every(1).seconds.do(
        execute_jobs,
        client,
        sessionmaker,
        storage,
    )
    scheduler.every(1).seconds.do(
        send_message,
        client,
        sessionmaker,
        storage,
    )
    scheduler.every(3).hours.do(
        update_bot_name,
        client,
        sessionmaker,
        storage,
    )


async def cache_bot_identity(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
    path_session: str,
) -> int | None:
    async with sessionmaker() as session:
        row = await session.execute(
            select(UserBot.id, UserBot.user_manager_id).where(UserBot.path_session == path_session).limit(1)
        )
        bot_row = row.first()

    if bot_row is None:
        logger.error(
            "Не найден аккаунт с path_session=%s — записать в Redis нечего",
            path_session,
        )
        return None

    bot_id, manager_id = bot_row

    await storage.set("bot_id", bot_id)
    logger.info("Записали bot_id=%s в Redis для текущей сессии", bot_id)

    if manager_id is not None:
        await storage.set("user_manager_id", manager_id)
        logger.info("Записали user_manager_id=%s в Redis для текущей сессии", manager_id)
    else:
        logger.warning(
            "У аккаунта id=%s отсутствует user_manager_id — antiflood/правила могут не работать",
            bot_id,
        )

    return bot_id


async def init_telethon_client() -> TelegramClient | None:
    """Инициализация Telegram клиента"""
    try:
        client = TelegramClient(bot_path_session, bot_api_id, bot_api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("Сессия не авторизована")
            return None
        else:
            logger.info("Клиент Telegram инициализирован")
            return client
    except Exception as e:
        logger.exception(f"Ошибка при инициализации клиента: {e}")
        return None


async def main() -> None:
    global bot_path_session
    logger.info("Запуск...")

    prepared_session = ensure_session_writable(bot_path_session)
    if prepared_session is None:
        logger.error(
            "Останавливаем бота: нет прав на запись в файл сессии (%s)",
            bot_path_session,
        )
        return
    bot_path_session = prepared_session

    # Инициализация redis
    redis = await se.redis_dsn()

    # Инициализация клиентов БД
    engine, sessionmaker = await create_db_session_pool(se)

    client = await init_telethon_client()
    if not client:
        logger.error("Ошибка при инициализации клиента Telegram")
        exit()

    storage = RedisStorage(redis=redis, client_hash=bot_api_hash)

    bot_id = await cache_bot_identity(sessionmaker, storage, path_session=bot_path_session)
    if bot_id is None:
        logger.error("Останавливаем бота: нет привязки аккаунта к сессии")
        return

    # Обновляем имя аккаунта сразу при старте, если оно пустое или изменилось.
    await update_bot_name(client, sessionmaker, storage)

    await set_tasks(client, sessionmaker, storage)

    # Запуск планировщика и клиента
    try:
        logger.info("Запуск планировщика и клиента")
        await asyncio.gather(
            client.start(),  # pyright: ignore
            run_scheduler(),
        )
        await client.run_until_disconnected()  # pyright: ignore
    except Exception as e:
        logger.exception(f"Ошибка при запуске Клиента: {e}")
    finally:
        await client.disconnect()  # pyright: ignore
        logger.info("Клиент отключен")


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("schedule").setLevel(logging.WARNING)

    # Формат логов
    f = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )
    f.converter = _moscow_time_converter

    # Обработчик для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(f)
    logger.addHandler(console_handler)

    # Подавляем шумные логи Telethon об обновлениях каналов
    logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)

    asyncio.run(main())
