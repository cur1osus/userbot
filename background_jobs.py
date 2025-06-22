import datetime
import logging
from typing import Any, Final

import msgpack
from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import Job, JobName
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from telethon import TelegramClient
from utils.func import Function as fn  # noqa: N813

logger = logging.getLogger(__name__)
minute: Final[int] = 60


async def send_message(client: Any, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    users_per_minute = await fn.get_users_per_minute(sqlalchemy_client, redis_client, cashed=True)
    delay = minute // users_per_minute
    if datetime.datetime.now().second % delay == 0:  # noqa: DTZ005
        if not await fn.is_work(redis_client, sqlalchemy_client):
            logger.info("Отправка сообщения остановлена")
            return

        user = await fn.get_closer_data_user(sqlalchemy_client)
        if not user:
            logger.info("----")
            return
        ans = await fn.take_message_answer(redis_client, sqlalchemy_client)
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
    if not await fn.is_work(redis_client, sqlalchemy_client):
        logger.info("Анализ сообщений с канала остановлен")
        return
    channels = await fn.get_monitoring_chat(sqlalchemy_client, redis_client)
    channels = map(int, channels)
    for channel in channels:
        channel_entity = await fn.safe_get_entity(client, channel)
        if not hasattr(channel_entity, "broadcast"):
            continue
        updates = await fn.get_difference_update_channel(client, channel, redis_client)
        if not updates:
            continue
        for update in updates:
            msg_text = update.message
            triggers = await fn.get_keywords(sqlalchemy_client, redis_client, cashed=True)
            excludes = await fn.get_ignored_words(sqlalchemy_client, redis_client, cashed=True)
            if not await fn.is_acceptable_message(msg_text, triggers, excludes):
                logger.info(f"Сообщение не прошло проверку: {msg_text}")
                return
            mention = await fn.parse_mention(update.message)
            if not mention:
                logger.info(f"Сообщение не содержит упоминания: {msg_text}")
                return
            sender = await fn.safe_get_entity(client, mention)
            if not sender:
                return

            banned_users = await fn.get_banned_usernames(sqlalchemy_client)
            if sender.username and (f"@{sender.username}" in banned_users):
                logger.info(f"Пользователь {sender.username} находится в бане")
                return

            if await fn.user_exist(sender.id, sqlalchemy_client):
                logger.info(f"Пользователь {sender.id} уже есть в базе")
                return

            logger.info(f"Записал на отработку человека с этого канала: {channel_entity.title}")
            await fn.add_user_v2(sender, update, sqlalchemy_client)


task_func = {
    JobName.processed_users: fn.get_folder_chats,
    JobName.get_chat_title: fn.update_chat_title,
    JobName.get_me_name: fn.update_me_name,
}


async def execute_jobs(
    client: TelegramClient,
    redis_client: RedisClient,
    sqlalchemy_client: SQLAlchemyClient,
) -> None:  # sourcery skip: for-index-underscore
    async with sqlalchemy_client.session_factory() as session:
        jobs: list[Job] = await session.scalars(
            select(Job).where(Job.answer.is_(None)),
        )
        for job in jobs:
            if job.task == JobName.processed_users.value:
                r = await task_func[JobName.processed_users](client, "🧠") or "В папке пусто"
                job.answer = msgpack.packb(r)
            elif job.task == JobName.get_chat_title.value:
                await task_func[JobName.get_chat_title](client, session, job.bot_id)
                await session.delete(job)
            elif job.task == JobName.get_me_name.value:
                await task_func[JobName.get_me_name](client, session, job.bot_id)
                await session.delete(job)
        await session.commit()
