import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient, events
from telethon.tl.types import Channel, User
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage())
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        chats = await fn.get_monitoring_chat(sqlalchemy_client)
        if str(event.chat_id) not in chats:
            return

        msg_text = event.message.message
        sender: User | Channel = await event.get_sender()

        if not await fn.is_acceptable_message(msg_text, sqlalchemy_client):
            return

        if isinstance(sender, Channel):
            mention = await fn.parse_mention(event.message)
            if not mention:
                return
            try:
                sender = await client.get_entity(mention)
            except ValueError as e:
                logger.exception(f"Error fetching entity: {e}")
                return

        banned_users = await fn.get_banned_usernames(sqlalchemy_client)
        if sender.username and f"@{sender.username}" in banned_users:
            return

        if await fn.user_exist(sender.id, sqlalchemy_client):
            return

        await fn.add_user(sender, event, sqlalchemy_client)
