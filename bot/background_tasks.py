import datetime
import logging
from typing import Any, Final, cast

import msgpack  # type: ignore
from bot.db.func import RedisStorage
from bot.db.models import Bot as UserBot
from bot.db.models import Job, JobName, UserAnalyzed, UserManager
from bot.utils.func import Function as fn  # noqa: N813
from bot.utils.func import Status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient  # type: ignore

logger = logging.getLogger(__name__)
SECONDS_PER_MINUTE: Final[int] = 60
SessionFactory = async_sessionmaker[AsyncSession]


async def update_bot_name(
    client: TelegramClient,
    sessionmaker: SessionFactory,
    storage: RedisStorage,
) -> None:
    """
    Раз в 3 часа обновляет name аккаунта в БД по данным из Telegram.
    """
    bot_id = await _get_bot_id(storage)
    if bot_id is None:
        return

    me = await client.get_me()
    if not me:
        logger.warning("get_me вернул None — пропускаем обновление имени")
        return

    name_parts = [me.first_name or "", me.last_name or ""]
    new_name = " ".join(filter(None, name_parts)) or (me.username or "")
    if not new_name:
        logger.warning("Имя для обновления пустое — пропускаем")
        return

    async with sessionmaker() as session:
        userbot = await session.get(UserBot, bot_id)
        if not userbot:
            logger.error("Аккаунт id=%s не найден в БД, не обновляем имя", bot_id)
            return

        if userbot.name == new_name:
            logger.debug("Имя аккаунта id=%s уже актуально: %s", bot_id, new_name)
            return

        userbot.name = new_name
        await session.commit()
        logger.info("Обновили имя аккаунта id=%s на '%s'", bot_id, new_name)


async def send_message(
    client: Any,
    sessionmaker: SessionFactory,
    redis_storage: RedisStorage,
) -> None:
    """Отправка сообщения очередному пользователю с соблюдением лимита."""
    async with sessionmaker() as session:
        users_per_minute = int(await fn.get_users_per_minute(session, redis_storage, cashed=True) or 1)
        if users_per_minute <= 0:
            logger.warning("Некорректный лимит отправки сообщений: %s", users_per_minute)
            users_per_minute = 1
        delay = max(1, SECONDS_PER_MINUTE // users_per_minute)
        if not _should_send_now(delay):
            return
        if not await fn.is_work(redis_storage, session):
            logger.info("Отправка сообщения остановлена")
            return
        bot_id = await _get_bot_id(redis_storage)
        if bot_id is None:
            return
        user_manager = await _get_user_manager(session, redis_storage)
        if not user_manager:
            return
        if user_manager.is_antiflood_mode:
            logger.debug("Antiflood mode включен, отправка сообщений пропущена")
            return
        user = await fn.get_closer_data_user(session, bot_id)
        if not user:
            logger.debug("Нет пользователей в очереди на отправку")
            return
        ans = await fn.take_message_answer(redis_storage, session)
        await _send_message(
            client,
            user,
            ans,
            sessionmaker,
            bot_id,
            session,
            redis_storage,
        )
        await session.commit()


async def handling_difference_update_chanel(
    client: TelegramClient,
    sessionmaker: SessionFactory,
    redis_storage: RedisStorage,
) -> None:
    """Обрабатывает новые сообщения в отслеживаемых каналах."""
    async with sessionmaker() as session:
        if not await fn.is_work(redis_storage, session):
            logger.info("Анализ сообщений с канала остановлен")
            return
        bot_id = await _get_bot_id(redis_storage)
        if bot_id is None:
            logger.info("bot_id нет в redis")
            return
        channel_ids = map(int, await fn.get_monitoring_chat(session, bot_id))
        for channel_id in channel_ids:
            await _process_channel_updates(
                client=client,
                redis_storage=redis_storage,
                sessionmaker=sessionmaker,
                session=session,
                bot_id=bot_id,
                channel_id=channel_id,
            )


async def _send_message(
    client: TelegramClient,
    user: UserAnalyzed,
    ans: str,
    sessionmaker: SessionFactory,
    bot_id: int,
    session: AsyncSession,
    redis_storage: RedisStorage,
) -> None:
    r = await fn.send_message_random(
        client,
        user,
        ans,
        session=session,
        redis_storage=redis_storage,
    )
    if isinstance(r, Status):
        await fn.handle_status(
            sessionmaker=sessionmaker,
            status=r,
            bot_id=int(bot_id),
        )
        return
    if r:
        logger.info(f"Сообщение было отправлено успешно {user.username}")
        user.sended = True


async def execute_jobs(
    client: TelegramClient,
    sessionmaker: SessionFactory,
    redis_storage: RedisStorage,
) -> None:
    """Выполняет отложенные задания из таблицы jobs."""
    async with sessionmaker() as session:
        jobs: list[Job] = list(
            await session.scalars(
                select(Job).where(Job.answer.is_(None)),
            )
        )
        for job in jobs:
            await _process_job(job, client, session)
        await session.commit()


def _should_send_now(delay_seconds: int) -> bool:
    """Сигнализирует, настало ли время отправки сообщения."""
    return datetime.datetime.now().second % delay_seconds == 0  # noqa: DTZ005


async def _process_channel_updates(
    *,
    client: TelegramClient,
    redis_storage: RedisStorage,
    sessionmaker: SessionFactory,
    session: AsyncSession,
    bot_id: int,
    channel_id: int,
) -> None:
    channel_entity = await fn.safe_get_entity(
        client,
        channel_id,
        redis_storage=redis_storage,
        session=session,
        target="monitoring_chat",
    )
    if isinstance(channel_entity, Status):
        await fn.handle_status(sessionmaker, channel_entity, bot_id, channel_id)
        return

    if not hasattr(channel_entity, "broadcast"):
        return

    updates = await fn.get_difference_update_channel(client, channel_id, redis_storage)
    if not updates:
        return

    triggers = await fn.get_keywords(session, redis_storage, cashed=True)
    excludes = await fn.get_ignored_words(session, redis_storage, cashed=True)
    banned_usernames = set(await fn.get_banned_usernames(session, redis_storage))

    for update in updates:
        await _process_update(
            update=update,
            session=session,
            redis_storage=redis_storage,
            triggers=triggers,
            excludes=excludes,
            banned_usernames=banned_usernames,
        )


async def _process_update(
    *,
    update: Any,
    session: AsyncSession,
    redis_storage: RedisStorage,
    triggers: set[str],
    excludes: set[str],
    banned_usernames: set[str],
) -> None:
    msg_text = update.message
    if not msg_text:
        return

    is_acceptable, ignores, triggers_found = await fn.is_acceptable_message(msg_text, triggers, excludes)
    mention = await fn.parse_mention(update.message)

    if not mention or mention.endswith("bot"):
        return

    username = f"@{mention}"

    banned_username = None
    if username in banned_usernames:
        banned_username = username

    if await fn.user_exist(username, session):
        return

    data_for_decision = _build_decision_data(
        is_acceptable=is_acceptable,
        ignores=ignores,
        triggers=triggers_found,
        mention=mention,
        banned_username=banned_username,
    )

    await fn.add_user_v2(username, update, session, redis_storage, data_for_decision)


def _build_decision_data(
    *,
    is_acceptable: bool,
    ignores: list[str],
    triggers: list[str],
    mention: str | None,
    banned_username: str | None,
) -> dict[str, Any] | None:
    """Собирает данные, объясняющие, почему пользователь требует ручного решения."""
    decision_data: dict[str, Any] = {}

    if not is_acceptable:
        decision_data["ignores"] = ignores
        decision_data["triggers"] = triggers

    if mention is None:
        decision_data["not_mention"] = True

    if banned_username:
        decision_data["banned"] = banned_username
        decision_data["ignores"] = ignores
        decision_data["triggers"] = triggers

    return decision_data or None


async def _process_job(
    job: Job,
    client: TelegramClient,
    session: AsyncSession,
) -> None:
    match job.task:
        case JobName.get_folders.value:
            result = await fn.get_folders_chat(client)
            job.answer = cast(int, msgpack.packb(result))
        case JobName.processed_users.value:
            task_metadata = job.task_metadata or b""
            task_data = msgpack.unpackb(task_metadata) if task_metadata else {}
            result = await fn.get_processed_users(client, task_data)
            job.answer = cast(int, msgpack.packb(result))
        case JobName.get_chat_title.value:
            await fn.update_chat_title(client, session, job.bot_id)
            await session.delete(job)
        case JobName.get_me_name.value:
            await fn.update_me_name(client, session, job.bot_id)
            await session.delete(job)
        case _:
            logger.warning("Неизвестная задача %s, пропускаем", job.task)
            return


async def _get_bot_id(storage: RedisStorage) -> int | None:
    bot_id_raw = await storage.get("bot_id")
    try:
        return int(bot_id_raw)
    except (TypeError, ValueError):
        logger.warning("Не удалось определить bot_id (raw=%s)", bot_id_raw)
        return None


async def _get_user_manager(session: AsyncSession, redis_storage: RedisStorage) -> UserManager | None:
    user_manager_id = await redis_storage.get("user_manager_id")
    try:
        user_manager_id_int = int(user_manager_id)
    except (TypeError, ValueError):
        logger.warning("Некорректный user_manager_id в Redis: %s", user_manager_id)
        return None

    user_manager = await session.scalar(select(UserManager).where(UserManager.id == user_manager_id_int))
    if not user_manager:
        logger.info("User manager id=%s не найден в базе данных", user_manager_id_int)
        return None
    return user_manager
