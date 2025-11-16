import datetime
import logging
from typing import Any, Final, cast

import msgpack  # type: ignore
from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import Job, JobName
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from telethon import TelegramClient  # type: ignore
from utils.func import Function as fn  # noqa: N813
from utils.func import Status

logger = logging.getLogger(__name__)
minute: Final[int] = 60


async def send_message(client: Any, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        users_per_minute = await fn.get_users_per_minute(session, redis_client, cashed=True)
        delay = minute // users_per_minute
        if datetime.datetime.now().second % delay == 0:  # noqa: DTZ005
            if not await fn.is_work(redis_client, session):
                logger.info("Отправка сообщения остановлена")
                return
            bot_id = await redis_client.get("bot_id")
            if not bot_id:
                return
            user = await fn.get_closer_data_user(session, int(bot_id))
            if not user:
                logger.info("----")
                return
            ans = await fn.take_message_answer(redis_client, session)
            try:
                await fn.send_message_random(client, user, ans)
                logger.info(f"Сообщение было отправлено успешно {user.id_user}, {user.username}")
            except Exception as e:
                logger.info(f"Произошла ошибка при отправке сообщения: {e}\n")


async def handling_difference_update_chanel(
    client: TelegramClient,
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
) -> None:
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        if not await fn.is_work(redis_client, session):
            logger.info("Анализ сообщений с канала остановлен")
            return
        bot_id: int | None = await redis_client.get("bot_id")
        if not bot_id:
            logger.info("bot_id нет в redis")
            return
        channels_ids = await fn.get_monitoring_chat(session, bot_id)
        channels_ids = map(int, channels_ids)
        for channel_id in channels_ids:
            channel_entity = await fn.safe_get_entity(client, channel_id)
            if isinstance(channel_entity, Status):
                await fn.handle_status(sqlalchemy_client.session_factory, channel_entity, bot_id, channel_id)
                continue

            if not hasattr(channel_entity, "broadcast"):
                continue
            updates = await fn.get_difference_update_channel(client, channel_id, redis_client)
            if not updates:
                continue
            for update in updates:
                msg_text = update.message
                triggers = await fn.get_keywords(session, redis_client, cashed=True)
                excludes = await fn.get_ignored_words(session, redis_client, cashed=True)
                data_for_decision = {}

                is_acceptable, list_ignore_for_decision, list_trigger_for_decision = await fn.is_acceptable_message(
                    msg_text, triggers, excludes
                )
                if not is_acceptable:
                    data_for_decision["ignores"] = list_ignore_for_decision
                    data_for_decision["triggers"] = list_trigger_for_decision

                mention = await fn.parse_mention(update.message)
                if not mention:
                    data_for_decision["not_mention"] = True

                if mention and mention.endswith("bot"):
                    continue

                sender = await fn.safe_get_entity(client, mention)
                if isinstance(sender, Status):
                    await fn.handle_status(sqlalchemy_client.session_factory, sender, bot_id)
                    continue
                if not sender or isinstance(sender, Status):
                    continue

                banned_users = await fn.get_banned_usernames(session, redis_client)
                if sender.username and (f"@{sender.username}" in banned_users):
                    data_for_decision["banned"] = f"@{sender.username}"
                    data_for_decision["ignores"] = list_ignore_for_decision
                    data_for_decision["triggers"] = list_trigger_for_decision

                if await fn.user_exist(sender.id, session):
                    data_for_decision["already_exist"] = sender.username or sender.first_name
                    data_for_decision["ignores"] = list_ignore_for_decision
                    data_for_decision["triggers"] = list_trigger_for_decision

                data_for_decision = data_for_decision if len(data_for_decision) > 0 else None

                await fn.add_user_v2(sender, update, session, redis_client, data_for_decision)


task_func = {
    JobName.get_folders: fn.get_folders_chat,
    JobName.processed_users: fn.get_processed_users,
    JobName.get_chat_title: fn.update_chat_title,
    JobName.get_me_name: fn.update_me_name,
}


async def execute_jobs(
    client: TelegramClient,
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
) -> None:  # sourcery skip: for-index-underscore
    async with sqlalchemy_client.session_factory() as session:  # type ignore
        jobs: list[Job] = list(
            await session.scalars(
                select(Job).where(Job.answer.is_(None)),
            )
        )
        for job in jobs:
            if job.task == JobName.get_folders.value:
                r = await task_func[JobName.get_folders](client)
                job.answer = cast(int, msgpack.packb(r))
            if job.task == JobName.processed_users.value:
                task_metadata = msgpack.unpackb(job.task_metadata)
                r = await task_func[JobName.processed_users](client, task_metadata)
                job.answer = cast(int, msgpack.packb(r))
            elif job.task == JobName.get_chat_title.value:
                await task_func[JobName.get_chat_title](client, session, job.bot_id)
                await session.delete(job)
            elif job.task == JobName.get_me_name.value:
                await task_func[JobName.get_me_name](client, session, job.bot_id)
                await session.delete(job)
        await session.commit()
