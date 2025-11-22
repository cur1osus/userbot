import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient, events  # type: ignore
from telethon.tl.types import Chat, User  # type: ignore
from utils.func import Function as fn  # noqa: N813
from utils.func import Status


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
            triggers = await fn.get_keywords(session, redis_client, cashed=True)
            excludes = await fn.get_ignored_words(session, redis_client, cashed=True)
            data_for_decision = {}

            is_acceptable, found_ignores, found_triggers = await fn.is_acceptable_message(msg_text, triggers, excludes)
            if not is_acceptable:
                data_for_decision["ignores"] = found_ignores
                data_for_decision["triggers"] = found_triggers

            sender: User = await event.get_sender()
            if not sender:
                return

            mention = await fn.parse_mention(msg_text)
            if not mention:
                data_for_decision["not_mention"] = True

            banned_users = await fn.get_banned_usernames(session, redis_client)
            if sender.username and (f"@{sender.username}" in banned_users):
                data_for_decision["banned"] = f"@{sender.username}"

            if await fn.user_exist(sender.id, session):
                data_for_decision["already_exist"] = sender.username or sender.first_name

            chat = await fn.safe_get_entity(
                client,
                event.chat_id,
                redis_client=redis_client,
                session=session,
                target="monitoring_chat",
            )
            if isinstance(chat, Status):
                bot_id = await redis_client.get("bot_id")
                await fn.handle_status(session, chat, bot_id) if bot_id else None
            if not chat or isinstance(chat, Status):
                return
            if isinstance(chat, User):
                logger.info(f"Записал на отработку человека с этого юзера: {sender.id} {sender.username}")
            if isinstance(chat, Chat):
                logger.info(f"Записал на отработку человека с этого чата: {chat.title}")

            data_for_decision = data_for_decision if len(data_for_decision) > 0 else None

            await fn.add_user(sender, event, session, redis_client, data_for_decision)
