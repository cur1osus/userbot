import datetime
import logging
from typing import Any

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient
from utils.func import Function as fn  # noqa: N813

logger = logging.getLogger(__name__)


async def send_message(client: Any, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    if datetime.datetime.now().second == 0:  # noqa: DTZ005
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
    channels = await fn.get_monitoring_chat(sqlalchemy_client)
    channels = map(int, channels)
    for channel in channels:
        channel_entity = await client.get_entity(channel)
        if not hasattr(channel_entity, "broadcast"):
            continue
        updates = await fn.get_difference_update_channel(client, channel, redis_client)
        if not updates:
            continue
        for update in updates:
            msg_text = update.message
            if not await fn.is_acceptable_message(msg_text, sqlalchemy_client, redis_client):
                return
            mention = await fn.parse_mention(update.message)
            if not mention:
                return
            try:
                sender = await client.get_entity(mention)
            except ValueError as e:
                logger.exception(f"Error fetching entity: {e}")
                return

            banned_users = await fn.get_banned_usernames(sqlalchemy_client)
            if sender.username and (f"@{sender.username}" in banned_users):
                return

            if await fn.user_exist(sender.id, sqlalchemy_client):
                return

            logger.info(f"Записал на отработку человека с этого канала: {channel_entity.title}")
            await fn.add_user_v2(sender, update, sqlalchemy_client)
