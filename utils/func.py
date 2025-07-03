import contextlib
import logging
import random
import re
from typing import Any

from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import (
    BannedUser,
    Bot,
    IgnoredWord,
    KeyWord,
    MessageToAnswer,
    MonitoringChat,
    UserAnalyzed,
    UserManager,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient, events, functions  # type: ignore
from telethon.tl.functions.channels import GetFullChannelRequest  # type: ignore
from telethon.tl.functions.updates import GetChannelDifferenceRequest  # type: ignore
from telethon.tl.types import (  # type: ignore
    ChannelMessagesFilter,
    DialogFilter,
    InputChannel,
    Message,
    MessageRange,
    Channel,
)
from telethon.tl.types.updates import (  # type: ignore
    ChannelDifference,
    ChannelDifferenceEmpty,
    ChannelDifferenceTooLong,
)

logger = logging.getLogger(__name__)


class Function:
    @staticmethod
    async def get_closer_data_user(
        session: AsyncSession,
    ) -> UserAnalyzed | None:
        user = await session.scalar(
            select(UserAnalyzed).where(UserAnalyzed.sended.is_(False)).order_by(UserAnalyzed.id.asc()).limit(1),
        )

        if not user:
            return None
        user.sended = True
        await session.commit()
        return user

    @staticmethod
    async def send_message_two(client: Any, user: UserAnalyzed, ans: str) -> None:
        await client.send_message(entity=user.id_user, message=ans)
        await client.forward_messages(
            entity=user.id_user,
            messages=int(user.message_id),
            from_peer=int(user.chat_id),
        )

    @staticmethod
    async def send_message_four(client: Any, user: UserAnalyzed, ans: str) -> None:
        ans = f"{user.additional_message}\n\n{ans}"
        await client.send_message(entity=user.id_user, message=ans)

    @staticmethod
    async def send_message_random(client: Any, user: UserAnalyzed, ans: str) -> None:
        func = random.choices(
            population=[
                Function.send_message_two,
                Function.send_message_four,
            ],
            weights=[0.10, 0.90],
        )[0]

        await func(client, user, ans)

    @staticmethod
    async def parse_mention(text: str) -> str | None:
        """
        Извлекает username Telegram из текста.
        Username должен начинаться с @ и содержать буквы, цифры или подчеркивания (от 5 до 32 символов).

        Args:
            text (str): Входной текст, содержащий username Telegram.

        Returns:
            str or None: Найденный username Telegram или None, если username не найден.

        """
        pattern = r"@[A-Za-z0-9_]{5,32}\b"
        match = re.search(pattern, text)
        return match[0][1:] if match else None

    @staticmethod
    async def is_acceptable_message(message: str, triggers: set[str], excludes: set[str]) -> bool:
        message = message.lower().replace("\n", " ")
        triggers = {trigger.lower() for trigger in triggers}
        excludes = {exclude.lower() for exclude in excludes}
        r = any(keyword in message for keyword in triggers)
        return r and all(ignored_word not in message for ignored_word in excludes)

    @staticmethod
    async def take_message_answer(
        redis_client: RedisClient,
        session: AsyncSession,
    ) -> str:
        if r := await redis_client.get("messages_to_answer"):
            return random.choice(r)
        user_manager_id = await redis_client.get("user_manager_id")

        r = (
            await session.scalars(
                select(MessageToAnswer.sentence).where(MessageToAnswer.user_manager_id == user_manager_id),
            )
        ).all()
        if not r:
            return "Привет"
        await redis_client.save("messages_to_answer", r, 60)
        return random.choice(r)

    @staticmethod
    async def get_monitoring_chat(session: AsyncSession, redis_client: RedisClient) -> list[str]:
        bot_id = await redis_client.get("bot_id")
        return (await session.scalars(select(MonitoringChat.chat_id).where(MonitoringChat.bot_id == bot_id))).all()

    @staticmethod
    async def get_banned_usernames(session: AsyncSession, redis_client: RedisClient) -> list[str]:
        user_manager_id = await redis_client.get("user_manager_id")

        return (
            await session.scalars(select(BannedUser.username).where(BannedUser.user_manager_id == user_manager_id))
        ).all()

    @staticmethod
    async def get_ignored_words(
        session: AsyncSession,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> set[str]:
        if cashed and (r := await redis_client.get("ignored_words")):
            return r
        user_manager_id = await redis_client.get("user_manager_id")

        r = (
            await session.scalars(select(IgnoredWord.word).where(IgnoredWord.user_manager_id == user_manager_id))
        ).all()
        r = set(r)
        await redis_client.save("ignored_words", r, 60)
        return r

    @staticmethod
    async def get_keywords(
        session: AsyncSession,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> set[str]:
        if cashed and (r := await redis_client.get("keywords")):
            return r
        user_manager_id = await redis_client.get("user_manager_id")

        r = (await session.scalars(select(KeyWord.word).where(KeyWord.user_manager_id == user_manager_id))).all()
        r = set(r)
        await redis_client.save("keywords", r, 60)
        return r

    @staticmethod
    async def get_messages_to_answer(session: AsyncSession, redis_client: RedisClient) -> list[str]:
        user_manager_id = await redis_client.get("user_manager_id")

        return (
            await session.scalars(
                select(MessageToAnswer.sentence).where(MessageToAnswer.user_manager_id == user_manager_id),
            )
        ).all()

    @staticmethod
    async def get_users_per_minute(
        session: AsyncSession,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> int:
        if cashed and (r := await redis_client.get("users_per_minute")):
            return r
        user_manager_id = await redis_client.get("user_manager_id")
        r = await session.scalar(select(UserManager.users_per_minute).where(UserManager.id == user_manager_id))
        await redis_client.save("users_per_minute", r, 60)
        return r

    @staticmethod
    async def user_exist(
        id_user: int,
        session: AsyncSession,
    ) -> bool:
        return bool(await session.scalar(select(UserAnalyzed).where(UserAnalyzed.id_user == id_user)))

    @staticmethod
    async def add_user(
        sender: Any,
        event: events.NewMessage.Event,
        session: AsyncSession,
        redis_client: RedisClient,
    ) -> None:
        message = event.message.message
        bot_id = await redis_client.get("bot_id")

        user = UserAnalyzed(
            id_user=sender.id,
            message_id=event.message.id,
            chat_id=event.chat_id,
            additional_message=message,
            bot_id=bot_id,
        )
        if r := sender.username:
            user.username = r
        session.add(user)
        await session.commit()

    @staticmethod
    async def add_user_v2(
        sender: Any,
        update: Message,
        session: AsyncSession,
        redis_client: RedisClient,
    ) -> None:
        message = update.message
        bot_id = await redis_client.get("bot_id")

        user = UserAnalyzed(
            id_user=sender.id,
            message_id=update.id,
            chat_id=update.peer_id.channel_id,
            additional_message=message,
            bot_id=bot_id,
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
    ) -> list[Any]:
        """Получение обновлений для канала, используя GetChannelDifferenceRequest."""
        try:
            # Получение сущности канала
            channel = await Function.safe_get_entity(client, chat_id)
            if not channel:
                return []
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
            pts = int(pts)
            difference: ChannelDifference = await client(
                GetChannelDifferenceRequest(
                    channel=input_channel,
                    filter=ChannelMessagesFilter(ranges=[MessageRange(pts - 100, pts + 100)]),
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

            # Обновление pts в базе данных
            await redis_client.save(chat_id, difference.pts)

            return updates  # noqa: TRY300

        except Exception as e:
            logger.exception(f"Ошибка при получении обновлений для канала {chat_id}: {e}")
            return []

    @staticmethod
    async def safe_get_entity(client: TelegramClient, peer_id: int) -> Any | None:
        try:
            # Сначала пробуем получить пользователя напрямую
            return await client.get_entity(peer_id)
        except ValueError:
            logger.info(f"Пользователь {peer_id} не найден в кэше, обновляем диалоги...")

            try:
                # Обновляем кэш диалогов
                await client.get_dialogs()
                await client.catch_up()

                # Пробуем снова после обновления кэша
                return await client.get_entity(peer_id)
            except ValueError:
                logger.info(f"Пользователь {peer_id} всё ещё недоступен после обновления кэша")
                return None
            except Exception as e:
                logger.info(f"Ошибка при получении пользователя {peer_id}: {e}")
                return None

    @staticmethod
    async def get_folders_chat(client: TelegramClient) -> list[dict[str, Any]] | None:
        await client.catch_up()
        result = await client(functions.messages.GetDialogFiltersRequest())
        folders = result.filters
        return [
            {
                "name": folder.title.text,
                "include_peers": [i.user_id for i in folder.include_peers if getattr(i, "user_id", False)],
                "pinned_peers": [i.user_id for i in folder.pinned_peers if getattr(i, "user_id", False)],
            }
            for folder in folders
            if isinstance(folder, DialogFilter)
        ]

    @staticmethod
    async def get_processed_users(
        client: TelegramClient,
        folders: list[dict[str, list[dict[str, str] | str]]],
    ) -> list[dict[str, list[dict[str, str] | str]]] | None:
        await client.catch_up()
        for folder in folders:
            users = []
            for peer in folder.get("pinned_peers", []):
                user = await Function.safe_get_entity(client, peer)  # type: ignore
                if not user:
                    continue
                users.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "phone": user.phone,
                    },
                )
            folder["pinned_peers"] = users  # type: ignore
        return folders

    @staticmethod
    async def update_chat_title(client: TelegramClient, session: AsyncSession, bot_id: int) -> None:
        chats = await session.scalars(
            select(MonitoringChat).where(and_(MonitoringChat.bot_id == bot_id, MonitoringChat.title.is_(None))),
        )
        for chat in chats:
            chat_ = await Function.safe_get_entity(client, int(chat.chat_id))

            if not chat_:
                continue
            with contextlib.suppress(Exception):
                chat.title = chat_.title

    @staticmethod
    async def update_me_name(client: TelegramClient, session: AsyncSession, bot_id: int) -> None:
        bot = await session.get(Bot, bot_id)
        with contextlib.suppress(Exception):
            me = await client.get_me()
            bot.name = me.first_name

    @staticmethod
    async def is_work(redis_client: RedisClient, session: AsyncSession, ttl: int = 60) -> bool:
        if await redis_client.get("is_work"):
            return True

        bot_id = await redis_client.get("bot_id")
        r = await session.scalar(select(Bot.is_started).where(Bot.id == bot_id))
        await redis_client.save("is_work", r, ttl)
        return r
