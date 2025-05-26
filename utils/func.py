import logging
import random
from collections.abc import Callable
from typing import Any

from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import BannedUser, IgnoredWord, Keyword, MessageToAnswer, MonitoringChat
from db.sqlalchemy.models import User as UserDB
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import UsernameNotOccupiedError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.updates import GetChannelDifferenceRequest
from telethon.tl.types import (
    ChannelMessagesFilter,
    InputChannel,
    Message,
    MessageEntityMention,
    MessageRange,
    User,
)
from telethon.tl.types.updates import ChannelDifference, ChannelDifferenceEmpty, ChannelDifferenceTooLong

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
    async def send_message_one(client: Any, user: User, ans: str) -> None:
        await client.send_message(entity=user.id_user, message=ans)
        await client.forward_messages(
            entity=user.id_user,
            messages=int(user.message_id),
            from_peer=int(user.chat_id),
        )

    @staticmethod
    async def send_message_two(client: Any, user: UserDB, ans: str) -> None:
        await client.forward_messages(
            entity=user.id_user,
            messages=int(user.message_id),
            from_peer=int(user.chat_id),
        )
        await client.send_message(entity=user.id_user, message=ans)

    @staticmethod
    async def send_message_three(client: Any, user: UserDB, ans: str) -> None:
        ans = f"{ans}\n\n{user.additional_message}"
        await client.send_message(entity=user.id_user, message=ans)

    @staticmethod
    async def send_message_four(client: Any, user: UserDB, ans: str) -> None:
        ans = f"{user.additional_message}\n\n{ans}"
        await client.send_message(entity=user.id_user, message=ans)

    @staticmethod
    async def send_message_random(client: Any, user: UserDB, ans: str) -> None:
        func = random.choices(
            population=[
                Function.send_message_one,
                Function.send_message_two,
                Function.send_message_three,
                Function.send_message_four,
            ],
            weights=[0.15, 0.15, 0.35, 0.35],
        )[0]

        await func(client, user, ans)

    @staticmethod
    async def reset_users_sended_status(sqlalchemy_client: SQLAlchemyClient) -> None:
        async with sqlalchemy_client.session_factory() as session:
            await session.execute(select(UserDB).update().values(sended=False))
            await session.commit()

    @staticmethod
    def collect_in_text(iter_: list[Any], func: Callable, sep: str = ", ") -> str | None:
        if not iter_:
            return None
        if not func:
            return sep.join(str(item) for item in iter_)
        return sep.join(func(item) for item in iter_)

    @staticmethod
    def markdown_code_style(text: str) -> str:
        return f"`{text}`"

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
        if not msg.entities:
            return mention
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
    async def is_acceptable_message(
        message: str,
        sqlalchemy_client: SQLAlchemyClient,
        redis_client: RedisClient,
    ) -> bool:
        message = message.lower()
        keywords = await Function.get_keywords(sqlalchemy_client, redis_client, cashed=True)
        ignored_words = await Function.get_ignored_words(sqlalchemy_client, redis_client, cashed=True)
        r = any(keyword in message for keyword in keywords)
        return r and all(ignored_word not in message for ignored_word in ignored_words)

    @staticmethod
    async def get_me_cashed(client: Any, redis_client: RedisClient) -> int:
        if r := await redis_client.get("me"):
            return r
        me: int = (await client.get_me()).id
        await redis_client.save("me", me)
        return me

    @staticmethod
    def parse_command(message: str, sep: str = ",") -> list[str]:
        r = message.split(" ", 1)
        if len(r) == 1:
            return []
        r = r[1]
        return [r.strip() for r in r.split(sep) if r]

    @staticmethod
    def parse_title(message: str) -> str:
        return message.split("\n", 1)[0].strip()

    @staticmethod
    async def take_message_answer(redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> str:
        if r := await redis_client.get("messages_to_answer"):
            return random.choice(r)
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(MessageToAnswer.sentence))).all()
            if not r:
                return "Привет"
            await redis_client.save("messages_to_answer", r, 60)
            return random.choice(r)

    @staticmethod
    async def get_monitoring_chat(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(MonitoringChat.id_chat))).all()

    @staticmethod
    async def get_banned_usernames(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(BannedUser.username))).all()

    @staticmethod
    async def get_not_banned_usernames(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(BannedUser.username).where(BannedUser.is_banned.is_(False)))).all()

    @staticmethod
    async def get_ignored_words(
        sqlalchemy_client: SQLAlchemyClient,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> list[str]:
        if cashed and (r := await redis_client.get("ignored_words")):
            return r
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(IgnoredWord.word))).all()
            r = [x.lower() for x in r]
            await redis_client.save("ignored_words", r, 60)
            return r

    @staticmethod
    async def get_keywords(
        sqlalchemy_client: SQLAlchemyClient,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> list[str]:
        if cashed and (r := await redis_client.get("keywords")):
            return r
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(Keyword.word))).all()
            r = [x.lower() for x in r]
            await redis_client.save("keywords", r, 60)
            return r

    @staticmethod
    async def get_messages_to_answer(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(MessageToAnswer.sentence))).all()

    @staticmethod
    async def user_exist(id_user: int, sqlalchemy_client: SQLAlchemyClient) -> bool:
        async with sqlalchemy_client.session_factory() as session:
            return bool(await session.scalar(select(UserDB).where(UserDB.id_user == id_user)))

    @staticmethod
    async def add_user(sender: Any, event: events.NewMessage.Event, sqlalchemy_client: SQLAlchemyClient) -> None:
        title = Function.parse_title(event.message.message)
        async with sqlalchemy_client.session_factory() as session:
            user = UserDB(
                id_user=sender.id,
                message_id=event.message.id,
                chat_id=event.chat_id,
                additional_message=title,
            )
            if r := sender.username:
                user.username = r
            session.add(user)
            await session.commit()

    @staticmethod
    async def add_user_v2(sender: Any, update: Message, sqlalchemy_client: SQLAlchemyClient) -> None:
        title = Function.parse_title(update.message)
        async with sqlalchemy_client.session_factory() as session:
            user = UserDB(
                id_user=sender.id,
                message_id=update.id,
                chat_id=update.peer_id.channel_id,
                additional_message=title,
            )
            if r := sender.username:
                user.username = r
            session.add(user)
            await session.commit()

    @staticmethod
    async def get_difference_update_channel(
        client: TelegramClient,
        chat_id: int,
        redis_client: RedisClient,
    ) -> list:
        """Получение обновлений для канала, используя GetChannelDifferenceRequest."""
        try:
            # Получение сущности канала
            channel = await client.get_entity(chat_id)
            input_channel = InputChannel(channel.id, channel.access_hash)

            # Получение или инициализация pts из базы данных

            chat_pts = await redis_client.get(chat_id)
            if chat_pts:
                pts = chat_pts
            else:
                # Инициализация pts через GetFullChannelRequest
                full_channel = await client(GetFullChannelRequest(input_channel))
                pts = full_channel.full_chat.pts
                await redis_client.save(chat_id, pts)

            # Запрос разницы для канала
            difference: ChannelDifference = await client(
                GetChannelDifferenceRequest(
                    channel=input_channel,
                    filter=ChannelMessagesFilter(ranges=[MessageRange(0, pts + 100)]),
                    pts=pts,
                    limit=100,  # Увеличенный лимит для захвата до 100 сообщений
                    force=False,
                ),
            )

            if isinstance(difference, ChannelDifferenceEmpty):
                logger.info(f"Состояние канала {chat_id} актуально, pts={pts}")
                return []
            if isinstance(difference, ChannelDifferenceTooLong):
                logger.warning(f"Состояние канала {chat_id} устарело, pts={pts} слишком старый")
                # Сброс pts до актуального значения
                full_channel = await client(GetFullChannelRequest(input_channel))
                await redis_client.save(chat_id, full_channel.full_chat.pts)
                return []

            # Обработка обновлений
            updates = []
            if difference.new_messages:
                updates.extend(difference.new_messages)
                logger.info(f"Канал {chat_id}: получено {len(difference.new_messages)} новых сообщений")
            # if difference.other_updates:
            #     updates.extend(difference.other_updates)
            #     logger.info(f"Канал {chat_id}: получено {len(difference.other_updates)} других обновлений")

            # Обновление pts в базе данных
            await redis_client.save(chat_id, difference.pts)

            return updates  # noqa: TRY300

        except Exception as e:
            logger.exception(f"Ошибка при получении обновлений для канала {chat_id}: {e}")
            return []
