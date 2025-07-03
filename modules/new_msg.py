import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient, events  # type: ignore
from telethon.tl.types import Chat, User  # type: ignore
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage())
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        async with sqlalchemy_client.session_factory() as session:  # type ignore
            chats = await fn.get_monitoring_chat(session, redis_client)
            if str(event.chat_id) not in chats:
                return
            if await redis_client.get(event.chat_id):
                return

            msg_text = event.message.message
            sender: User = await event.get_sender()
            triggers = fn.get_keywords(session, redis_client, cashed=True)
            excludes = fn.get_ignored_words(session, redis_client, cashed=True)
            if not await fn.is_acceptable_message(msg_text, triggers, excludes):
                return

            banned_users = await fn.get_banned_usernames(session, redis_client)
            if sender.username and (f"@{sender.username}" in banned_users):
                return

            if await fn.user_exist(sender.id, session):
                return

            chat = await fn.safe_get_entity(client, event.chat_id)
            if not chat:
                return
            if isinstance(chat, User):
                logger.info(f"Записал на отработку человека с этого юзера: {sender.id} {sender.username}")
            if isinstance(chat, Chat):
                logger.info(f"Записал на отработку человека с этого чата: {chat.title}")

            await fn.add_user(sender, event, session, redis_client)
