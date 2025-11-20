import datetime
import logging
from typing import TYPE_CHECKING, Any, Final, cast

import msgpack  # type: ignore
from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import Job, JobName, UserAnalyzed, UserManager
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient  # type: ignore
from utils.func import Function as fn  # noqa: N813
from utils.func import Status

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
SECONDS_PER_MINUTE: Final[int] = 60


async def send_message(client: Any, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    """Отправка сообщения очередному пользователю с соблюдением лимита."""
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        users_per_minute = await fn.get_users_per_minute(session, redis_client, cashed=True)
        delay = SECONDS_PER_MINUTE // users_per_minute
        if not _should_send_now(delay):
            return
        if not await fn.is_work(redis_client, session):
            logger.info("Отправка сообщения остановлена")
            return
        bot_id = await redis_client.get("bot_id")
        user_manager_id = await redis_client.get("user_manager_id")
        if not bot_id:
            return
        user = await fn.get_closer_data_user(session, int(bot_id))
        if not user:
            logger.info("----")
            return
        ans = await fn.take_message_answer(redis_client, session)
        user_manager = await session.scalar(select(UserManager).where(UserManager.id == user_manager_id))
        if not user_manager:
            logger.info("User manager не найден в базе данных")
            return
        if user_manager.is_antiflood_mode:
            users = await fn.get_closer_data_users(session, int(bot_id), limit=user_manager.limit_pack)
            if len(users) >= user_manager.limit_pack:
                users_to_text = ", \n".join([f"{user.username}" for user in users])
                j = Job(
                    task="send_pack_users",
                    task_metadata=users_to_text,
                    bot_id=bot_id,
                )
                session.add(j)

                for user in users:
                    user.sended = True

                await session.commit()
        else:
            await _send_message(
                client,
                user,
                ans,
                sqlalchemy_client.session_factory,
                bot_id,
            )
            await session.commit()


async def handling_difference_update_chanel(
    client: TelegramClient,
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
) -> None:
    """Обрабатывает новые сообщения в отслеживаемых каналах."""
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        if not await fn.is_work(redis_client, session):
            logger.info("Анализ сообщений с канала остановлен")
            return
        bot_id: int | None = await redis_client.get("bot_id")
        if not bot_id:
            logger.info("bot_id нет в redis")
            return
        channel_ids = map(int, await fn.get_monitoring_chat(session, bot_id))
        for channel_id in channel_ids:
            await _process_channel_updates(
                client=client,
                redis_client=redis_client,
                sqlalchemy_client=sqlalchemy_client,
                session=session,
                bot_id=bot_id,
                channel_id=channel_id,
            )


async def _send_message(client, user, ans, sessionmaker, bot_id):
    r = await fn.send_message_random(client, user, ans)
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
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
) -> None:  # sourcery skip: for-index-underscore
    """Выполняет отложенные задания из таблицы jobs."""
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        jobs: list[Job] = list(
            await session.scalars(
                select(Job).where(Job.answer.is_(None)),
            )
        )
        for job in jobs:
            await _process_job(job, client, session, redis_client.get("user_manager_id"))
        await session.commit()


def _should_send_now(delay_seconds: int) -> bool:
    """Сигнализирует, настало ли время отправки сообщения."""
    return datetime.datetime.now().second % delay_seconds == 0  # noqa: DTZ005


async def _process_channel_updates(
    *,
    client: TelegramClient,
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
    session: AsyncSession,
    bot_id: int,
    channel_id: int,
) -> None:
    channel_entity = await fn.safe_get_entity(client, channel_id)
    if isinstance(channel_entity, Status):
        await fn.handle_status(sqlalchemy_client.session_factory, channel_entity, bot_id, channel_id)
        return

    if not hasattr(channel_entity, "broadcast"):
        return

    updates = await fn.get_difference_update_channel(client, channel_id, redis_client)
    if not updates:
        return

    for update in updates:
        await _process_update(
            update=update,
            client=client,
            sqlalchemy_client=sqlalchemy_client,
            session=session,
            redis_client=redis_client,
            bot_id=bot_id,
        )


async def _process_update(
    *,
    update: Any,
    client: TelegramClient,
    sqlalchemy_client: SQLAlchemyClient,
    session: AsyncSession,
    redis_client: RedisClient,
    bot_id: int,
) -> None:
    msg_text = update.message
    triggers = await fn.get_keywords(session, redis_client, cashed=True)
    excludes = await fn.get_ignored_words(session, redis_client, cashed=True)

    is_acceptable, ignores, triggers_found = await fn.is_acceptable_message(msg_text, triggers, excludes)
    mention = await fn.parse_mention(update.message)

    if not mention or mention.endswith("bot"):
        return

    username = f"@{mention}"

    banned_username = None
    banned_users = await fn.get_banned_usernames(session, redis_client)
    if username in banned_users:
        banned_username = username

    existing_user = None
    if await fn.user_exist(username, session):
        existing_user = username

    data_for_decision = _build_decision_data(
        is_acceptable=is_acceptable,
        ignores=ignores,
        triggers=triggers_found,
        mention=mention,
        banned_username=banned_username,
        existing_user=existing_user,
    )

    await fn.add_user_v2(username, update, session, redis_client, data_for_decision)


def _build_decision_data(
    *,
    is_acceptable: bool,
    ignores: list[str],
    triggers: list[str],
    mention: str | None,
    banned_username: str | None,
    existing_user: str | None,
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

    if existing_user:
        decision_data["already_exist"] = existing_user
        decision_data["ignores"] = ignores
        decision_data["triggers"] = triggers

    return decision_data or None


async def _process_job(
    job: Job,
    client: TelegramClient,
    session: AsyncSession,
    user_manager_id: int | None = None,
) -> None:
    if job.task == JobName.get_folders.value:
        result = await fn.get_folders_chat(client)
        job.answer = cast(int, msgpack.packb(result))
        return

    if job.task == JobName.processed_users.value:
        task_metadata = msgpack.unpackb(job.task_metadata)
        result = await fn.get_processed_users(client, task_metadata)
        job.answer = cast(int, msgpack.packb(result))
        return

    if job.task == JobName.get_chat_title.value:
        await fn.update_chat_title(client, session, job.bot_id)
        await session.delete(job)
        return

    if job.task == JobName.get_me_name.value:
        await fn.update_me_name(client, session, job.bot_id)
        await session.delete(job)

    if job.task == "request_send_pack_users":
        if user_manager_id is None:
            logger.error("user_manager_id не найден в редисе")
            return
        usernames = msgpack.unpackb(job.task_metadata)
        for username in usernames:
            user_db = await session.scalar(select(UserAnalyzed).where(UserAnalyzed.username == username))
            if user_db is None:
                continue
            user_db.sended = False
        user_manager = await session.get(UserManager, user_manager_id)
        if not user_manager:
            logger.error("user_manager не найден в базе данных")
            return
        user_manager.is_antiflood_mode = False
        await session.commit()
