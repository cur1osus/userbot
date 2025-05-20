import logging
import random
from typing import Any

from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import BannedUser, IgnoredWord, Keyword, MessageToAnswer, MonitoringChat
from db.sqlalchemy.models import User as UserDB
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from telethon import events
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.types import Message, MessageEntityMention, User

logger = logging.getLogger(__name__)


class Function:
    @staticmethod
    async def get_closer_data_user(sqlalchemy_client: SQLAlchemyClient) -> UserDB | None:
        async with sqlalchemy_client.session_factory() as session:
            user = await session.scalar(
                select(UserDB).where(UserDB.sended.is_(False)).order_by(UserDB.id.asc()).limit(1),
            )
            if not user:
                return None
            user.sended = True
            await session.commit()
            return user

    @staticmethod
    async def block_user(client: Any, user: User) -> None:
        try:
            await client(BlockRequest(user))
            logger.info(f"Пользователь с username {user.username} был успешно заблокирован.")
        except Exception as e:
            logger.info(f"Произошла ошибка при блокировке пользователя: {e}")

    @staticmethod
    async def unblock_user(client: Any, user: User) -> None:
        try:
            await client(UnblockRequest(user))
            logger.info(f"Пользователь с username {user.username} был успешно разблокирован.")
        except UsernameNotOccupiedError as e:
            logger.info(f"Произошла ошибка при разблокировке пользователя: {e}")

    @staticmethod
    async def parse_mention(msg: Message) -> str | None:
        msg_text = msg.message
        mention = None
        for entity in msg.entities:
            if isinstance(entity, MessageEntityMention):
                offset = entity.offset + 1
                mention = msg_text[offset : entity.offset + entity.length]
        return mention

    @staticmethod
    async def extract_ids_message(event: events.NewMessage.Event) -> None:
        from_chat = event.chat_id
        message_id = event.message.id
        return f"{from_chat}:{message_id}"

    @staticmethod
    async def is_acceptable_message(message: str, sqlalchemy_client: SQLAlchemyClient) -> bool:
        message = message.lower()
        keywords = await Function.get_keywords(sqlalchemy_client)
        ignored_words = await Function.get_ignored_words(sqlalchemy_client)
        return any(keyword.lower() in message for keyword in keywords) and not any(
            ignored_word.lower() in message for ignored_word in ignored_words
        )

    @staticmethod
    def parse_command(message: str) -> list[str]:
        r = message.split(" ", 1)
        if len(r) == 1:
            return []
        r = r[1]
        return [r.strip() for r in r.split(",") if r]

    @staticmethod
    async def take_message_answer(redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> str:
        sessionmaker = sqlalchemy_client.session_factory
        if r := await redis_client.get("messages_to_answer"):
            return random.choice(r)
        async with sessionmaker() as session:
            r = (await session.scalars(select(MessageToAnswer.sentence))).all()
            if not r:
                return "Привет"
            await redis_client.save("messages_to_answer", r, 60)
            return random.choice(r)

    @staticmethod
    async def get_monitoring_chat(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(MonitoringChat.id_chat))).all()

    @staticmethod
    async def get_banned_usernames(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(BannedUser.username))).all()

    @staticmethod
    async def get_not_banned_usernames(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(BannedUser.username).where(BannedUser.is_banned.is_(False)))).all()

    @staticmethod
    async def get_ignored_words(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(IgnoredWord.word))).all()

    @staticmethod
    async def get_keywords(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(Keyword.word))).all()

    @staticmethod
    async def get_messages_to_answer(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return (await session.scalars(select(MessageToAnswer.sentence))).all()

    @staticmethod
    async def user_exist(id_user: int, sqlalchemy_client: SQLAlchemyClient) -> bool:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            return bool(await session.scalar(select(UserDB).where(UserDB.id_user == id_user)))

    @staticmethod
    async def add_user(sender: Any, event: Any, sqlalchemy_client: SQLAlchemyClient) -> None:
        sessionmaker = sqlalchemy_client.session_factory
        async with sessionmaker() as session:
            user = UserDB(
                id_user=sender.id,
                message_id=event.message.id,
                chat_id=event.chat_id,
            )
            if r := sender.username:
                user.username = r
            session.add(user)
            await session.commit()
