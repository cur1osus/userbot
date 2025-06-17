import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient, events
from telethon.tl.types import Chat, User
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage())
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        chats = await fn.get_monitoring_chat(sqlalchemy_client, redis_client)
        if str(event.chat_id) not in chats:
            return
        if await redis_client.get(event.chat_id):
            return

        msg_text = event.message.message
        sender: User = await event.get_sender()
        triggers = fn.get_keywords(sqlalchemy_client, redis_client, cashed=True)
        excludes = fn.get_ignored_words(sqlalchemy_client, redis_client, cashed=True)
        if not await fn.is_acceptable_message(msg_text, triggers, excludes):
            return

        banned_users = await fn.get_banned_usernames(sqlalchemy_client)
        if sender.username and (f"@{sender.username}" in banned_users):
            return

        if await fn.user_exist(sender.id, sqlalchemy_client):
            return

        chat = await fn.safe_get_entity(client, event.chat_id)
        if not chat:
            return
        if isinstance(chat, User):
            logger.info(f"Записал на отработку человека с этого юзера: {sender.id} {sender.username}")
        if isinstance(chat, Chat):
            logger.info(f"Записал на отработку человека с этого чата: {chat.title}")

        await fn.add_user(sender, event, sqlalchemy_client)
