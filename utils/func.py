import contextlib
import logging
import random
import re
from dataclasses import dataclass
from typing import Any

import msgpack
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
from telethon.errors import ChannelPrivateError, FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest  # type: ignore
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.updates import GetChannelDifferenceRequest  # type: ignore
from telethon.tl.types import (  # type: ignore
    ChannelMessagesFilter,
    DialogFilter,
    InputChannel,
    Message,
    MessageRange,
)
from telethon.tl.types.updates import (  # type: ignore
    ChannelDifferenceEmpty,
    ChannelDifferenceTooLong,
)

logger = logging.getLogger(__name__)


@dataclass
class Status:
    ok: bool
    message: str = ""


class Function:
    @staticmethod
    async def get_closer_data_user(session: AsyncSession, bot_id: int) -> UserAnalyzed | None:
        user = await session.scalar(
            select(UserAnalyzed)
            .where(
                and_(
                    UserAnalyzed.accepted.is_(True),
                    UserAnalyzed.sended.is_(False),
                    UserAnalyzed.bot_id == bot_id,
                )
            )
            .order_by(UserAnalyzed.id.asc())
            .limit(1),
        )

        if not user:
            return None
        user.sended = True
        await session.commit()
        return user

    @staticmethod
    async def send_message_two(client: TelegramClient, user: UserAnalyzed, ans: str) -> None:
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
    async def is_acceptable_message(
        message: str, triggers: set[str], excludes: set[str]
    ) -> tuple[bool, list[str], list[str]]:
        message_clean = message.lower().replace("\n", " ")
        triggers_lower = {trigger.lower() for trigger in triggers}
        excludes_lower = {exclude.lower() for exclude in excludes}

        # Проверяем, есть ли хотя бы один триггер
        has_trigger = any(keyword in message_clean for keyword in triggers_lower)

        # Находим все слова из excludes, присутствующие в сообщении
        found_ignores = {word for word in excludes_lower if word in message_clean}
        found_trigger = {word for word in triggers_lower if word in message_clean}

        # Сообщение допустимо, если есть триггер и НЕТ ни одного слова из исключений
        is_acceptable = has_trigger and (len(found_ignores) == 0)

        return is_acceptable, list(found_ignores), list(found_trigger)

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
        return bool(
            await session.scalar(
                select(UserAnalyzed).where(
                    and_(
                        UserAnalyzed.id_user == id_user,
                        UserAnalyzed.accepted.is_(True),
                        UserAnalyzed.sended.is_(True),
                    )
                )
            )
        )

    @staticmethod
    async def add_user(
        sender: Any,
        event: events.NewMessage.Event,
        session: AsyncSession,
        redis_client: RedisClient,
        data_for_decision: dict[str, Any] | None,
    ) -> None:
        message = event.message.message
        bot_id = await redis_client.get("bot_id")

        if r := await session.scalar(select(UserAnalyzed).where(UserAnalyzed.id_user == sender.id)):
            return

        user = UserAnalyzed(
            id_user=sender.id,
            message_id=event.message.id,
            chat_id=event.chat_id,
            additional_message=message,
            bot_id=bot_id,
        )
        if data_for_decision:
            user.decision = msgpack.packb(data_for_decision)
            user.accepted = False
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
        data_for_decision: dict[str, Any] | None,
    ) -> None:
        message = update.message
        bot_id = await redis_client.get("bot_id")

        if r := await session.scalar(select(UserAnalyzed).where(UserAnalyzed.id_user == sender.id)):
            return

        user = UserAnalyzed(
            id_user=sender.id,
            message_id=update.id,
            chat_id=update.peer_id.channel_id,
            additional_message=message,
            bot_id=bot_id,
        )
        if data_for_decision:
            user.decision = msgpack.packb(data_for_decision)
            user.accepted = False
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
        """Улучшенное получение обновлений для канала с максимальным охватом сообщений."""
        try:
            channel = await Function.safe_get_entity(client, chat_id)
            if not channel:
                return []

            input_channel = InputChannel(channel.id, channel.access_hash)
            chat_pts = await redis_client.get(chat_id)

            # Инициализация PTS через GetFullChannelRequest при первом запуске
            if not chat_pts:
                full_channel = await client(GetFullChannelRequest(input_channel))
                pts = full_channel.full_chat.pts
                await redis_client.save(chat_id, pts)
                logger.info(f"Инициализирован PTS={pts} для канала {chat_id}")
            else:
                pts = int(chat_pts)

            # Запрос разницы БЕЗ фильтра (критически важно!)
            MAX_MESSAGE_ID = 2**31 - 1  # Макс. значение для 32-bit signed int (Telegram использует 32-bit ID)
            filter = ChannelMessagesFilter(ranges=[MessageRange(0, MAX_MESSAGE_ID)], exclude_new_messages=False)
            difference = await client(
                GetChannelDifferenceRequest(
                    channel=input_channel,
                    filter=filter,
                    pts=pts,
                    limit=100,  # Макс. лимит Telegram API
                    force=True,  # Гарантируем получение изменений
                )
            )

            # Обработка случаев
            if isinstance(difference, ChannelDifferenceEmpty):
                logger.debug(f"Канал {chat_id}: состояние актуально (PTS={pts})")
                return []

            if isinstance(difference, ChannelDifferenceTooLong):
                logger.warning(f"Канал {chat_id}: PTS={pts} сильно устарел. Получаем историю...")
                return await Function._handle_too_long_state(client, input_channel, redis_client, chat_id)

            # Сбор ВСЕХ сообщений (включая other_updates)
            updates = difference.new_messages.copy()
            if hasattr(difference, "other_updates") and difference.other_updates:
                updates.extend(
                    [
                        update.message
                        for update in difference.other_updates
                        if hasattr(update, "message") and update.message
                    ]
                )

            # Обновление PTS только если есть изменения
            if difference.pts > pts:
                await redis_client.save(chat_id, difference.pts)
                logger.info(
                    f"Канал {chat_id}: получено {len(updates)} сообщений. PTS обновлен: {pts} → {difference.pts}"
                )
            else:
                logger.warning(
                    f"Канал {chat_id}: PTS не увеличился ({pts} → {difference.pts}). Возможно, ошибка синхронизации."
                )

            return updates

        except Exception as e:
            logger.exception(f"Критическая ошибка при обработке канала {chat_id}: {e}")
            return []

    @staticmethod
    async def _handle_too_long_state(
        client: TelegramClient,
        input_channel: InputChannel,
        redis_client: RedisClient,
        chat_id: int,
    ) -> list[Any]:
        """Обработка устаревшего PTS через историю сообщений"""
        try:
            # Получаем последние 100 сообщений (максимум за один запрос)
            history = await client(
                GetHistoryRequest(
                    peer=input_channel,
                    limit=100,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0,
                )
            )

            # Обновляем PTS до актуального
            full_channel = await client(GetFullChannelRequest(input_channel))
            new_pts = full_channel.full_chat.pts
            await redis_client.save(chat_id, new_pts)

            logger.warning(
                f"Канал {chat_id}: восстановлено {len(history.messages)} сообщений "
                f"из истории после PTS устаревания (новый PTS={new_pts})"
            )
            return history.messages

        except Exception as e:
            logger.error(f"Ошибка при обработке ChannelDifferenceTooLong для {chat_id}: {e}")
            return []

    @staticmethod
    async def handle_status(session: AsyncSession, status: Status, bot_id: int):
        match status.message:
            case "ChannelPrivateError":
                session.add(
                    Job(
                        bot_id=bot_id,
                        task="delete_private_channel",
                        task_metadata=msgpack.packb(channel),
                    )
                )
            case "ConnectionError":
                session.add(
                    Job(
                        bot_id=bot_id,
                        task="connection_error",
                    )
                )

    @staticmethod
    async def safe_get_entity(client: TelegramClient, peer_id: int | None) -> Any | None:
        if peer_id is None:
            return None
        try:
            # Сначала пробуем получить пользователя напрямую
            return await client.get_entity(peer_id)
        except ChannelPrivateError:
            logger.error(f"Ошибка при получении пользователя {peer_id}: ChannelPrivateError")
            return Status(ok=False, message="ChannelPrivateError")
        except ConnectionError as e:
            logger.error(f"Ошибка при получении пользователя {peer_id}: {e}")
            return Status(ok=False, message="ConnectionError")
        except FloodWaitError as e:
            logger.info(f"Пользователь {peer_id} временно недоступен из-за FloodWaitError: {e}")
            return Status(ok=False, message="FloodWaitError")
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
                return Status(ok=False, message="UserNotFound")
            except Exception as e:
                logger.info(f"Ошибка при получении пользователя {peer_id}: {e}")
                return Status(ok=False, message="UnknownError")

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
