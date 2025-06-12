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
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import select
from telethon import TelegramClient, events, functions
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.updates import GetChannelDifferenceRequest
from telethon.tl.types import (
    ChannelMessagesFilter,
    DialogFilter,
    InputChannel,
    InputPeerUser,
    Message,
    MessageRange,
)
from telethon.tl.types.updates import ChannelDifference, ChannelDifferenceEmpty, ChannelDifferenceTooLong

logger = logging.getLogger(__name__)


class Function:
    @staticmethod
    async def get_closer_data_user(sqlalchemy_client: SQLAlchemyClient) -> UserAnalyzed | None:
        async with sqlalchemy_client.session_factory() as session:
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
    async def reset_users_sended_status(sqlalchemy_client: SQLAlchemyClient) -> None:
        async with sqlalchemy_client.session_factory() as session:
            await session.execute(select(UserAnalyzed).update().values(sended=False))
            await session.commit()

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

    # @staticmethod
    # async def normalize_set(items: set) -> set:
    #     """
    #     Приводит набор слов или предложений к единому стандарту.
    #     :param items: Набор слов или предложений.
    #     :return: Нормализованный набор.
    #     """
    #     normalized = set()
    #     for item in items:
    #         if normalized_item := re.sub(r"[^\w\s]", "", item.lower()).strip():
    #             normalized.add(normalized_item)
    #     return normalized

    @staticmethod
    async def is_acceptable_message(message: str, triggers: set, excludes: set) -> bool:
        message = message.lower().replace("\n", " ")
        triggers = {trigger.lower() for trigger in triggers}
        excludes = {exclude.lower() for exclude in excludes}
        r = any(keyword in message for keyword in triggers)
        return r and all(ignored_word not in message for ignored_word in excludes)

    # @staticmethod
    # async def is_acceptable_message(
    #     message: str,
    #     triggers: set,
    #     excludes: set,
    #     threshold_word: int = 2,
    #     threshold_sentence: float = 0.20,
    # ) -> bool:
    #     # sourcery skip: assign-if-exp, boolean-if-exp-identity, reintroduce-else, remove-unnecessary-cast
    #     """
    #     Проверяет, подходит ли сообщение, используя слова и предложения как триггеры/исключения.

    #     :param message: Строка сообщения.
    #     :param triggers: Множество слов или предложений-триггеров.
    #     :param excludes: Множество слов или предложений-исключений.
    #     :param threshold_word: Порог расстояния Левенштейна для слов.
    #     :param threshold_sentence: Максимальная доля ошибок для предложений.
    #     :return: True, если сообщение подходит, иначе False.
    #     """
    #     # Приведение текста к единому формату
    #     triggers = await Function.normalize_set(triggers)
    #     excludes = await Function.normalize_set(excludes)
    #     logger.info(f"{triggers=}, {excludes=}")
    #     formatted_message = re.sub(r"[^\w\s]", "", message.lower())
    #     logger.info(f"{formatted_message=}")
    #     words = formatted_message.split()
    #     sentences = [sentence.strip() for sentence in re.split(r"[.!?\n]", formatted_message) if sentence.strip()]
    #     logger.info(f"{words=}, {sentences=}")

    #     def is_similar_word(word: str, word_set: set) -> bool:
    #         """Проверяет, есть ли похожее слово в наборе с учетом расстояния Левенштейна."""
    #         return any(
    #             levenshtein_distance(word, target_word) <= threshold_word
    #             for target_word in word_set
    #             if len(target_word.split()) == 1
    #         )

    #     def is_similar_sentence(sentence: str, sentence_set: set) -> bool:
    #         """Проверяет, есть ли похожее предложение в наборе с учетом относительного расстояния."""
    #         return any(
    #             levenshtein_distance(sentence, target_sentence) / max(len(sentence), len(target_sentence))
    #             <= threshold_sentence
    #             for target_sentence in sentence_set
    #             if len(target_sentence.split()) > 1
    #         )

    #     # Проверяем исключающие слова и предложения
    #     if any(is_similar_word(word, excludes) for word in words) or any(
    #         is_similar_sentence(sentence, excludes) for sentence in sentences
    #     ):
    #         return False

    #     # Проверяем триггеры в словах и предложениях
    #     if any(is_similar_word(word, triggers) for word in words) or any(
    #         is_similar_sentence(sentence, triggers) for sentence in sentences
    #     ):
    #         return True

    #     return False

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
    async def get_monitoring_chat(sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> list[str]:
        bot_id = await redis_client.get("bot_id")
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(MonitoringChat.id_chat).where(MonitoringChat.bot_id == bot_id))).all()

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
    ) -> set:
        if cashed and (r := await redis_client.get("ignored_words")):
            return r
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(IgnoredWord.word))).all()
            r = set(r)
            await redis_client.save("ignored_words", r, 60)
            return r

    @staticmethod
    async def get_keywords(
        sqlalchemy_client: SQLAlchemyClient,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> set:
        if cashed and (r := await redis_client.get("keywords")):
            return r
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(KeyWord.word))).all()
            r = set(r)
            await redis_client.save("keywords", r, 60)
            return r

    @staticmethod
    async def get_messages_to_answer(sqlalchemy_client: SQLAlchemyClient) -> list[str]:
        async with sqlalchemy_client.session_factory() as session:
            return (await session.scalars(select(MessageToAnswer.sentence))).all()

    @staticmethod
    async def get_users_per_minute(
        sqlalchemy_client: SQLAlchemyClient,
        redis_client: RedisClient,
        cashed: bool = False,
    ) -> int:
        if cashed and (r := await redis_client.get("users_per_minute")):
            return r
        async with sqlalchemy_client.session_factory() as session:
            r = (await session.scalars(select(UserManager.users_per_minute))).all()
            r = max(r)
            await redis_client.save("users_per_minute", r, 60)
            return r

    @staticmethod
    async def user_exist(id_user: int, sqlalchemy_client: SQLAlchemyClient) -> bool:
        async with sqlalchemy_client.session_factory() as session:
            return bool(await session.scalar(select(UserAnalyzed).where(UserAnalyzed.id_user == id_user)))

    @staticmethod
    async def add_user(sender: Any, event: events.NewMessage.Event, sqlalchemy_client: SQLAlchemyClient) -> None:
        message = event.message.message
        async with sqlalchemy_client.session_factory() as session:
            user = UserAnalyzed(
                id_user=sender.id,
                message_id=event.message.id,
                chat_id=event.chat_id,
                additional_message=message,
            )
            if r := sender.username:
                user.username = r
            session.add(user)
            await session.commit()

    @staticmethod
    async def add_user_v2(sender: Any, update: Message, sqlalchemy_client: SQLAlchemyClient) -> None:
        message = update.message
        async with sqlalchemy_client.session_factory() as session:
            user = UserAnalyzed(
                id_user=sender.id,
                message_id=update.id,
                chat_id=update.peer_id.channel_id,
                additional_message=message,
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

    @staticmethod
    async def get_folder_chats(client: TelegramClient, name: str) -> list[dict] | None:
        result = await client(functions.messages.GetDialogFiltersRequest())
        users = []
        folders = result.filters
        for folder in folders:
            if not isinstance(folder, DialogFilter) or folder.title.text != name:
                continue
            for peer in folder.include_peers:
                if not isinstance(peer, InputPeerUser):
                    continue
                user = await client.get_entity(peer.user_id)
                users.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "phone": user.phone,
                    },
                )
        return users

    @staticmethod
    async def is_work(redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient, ttl: int = 60) -> bool:
        if await redis_client.get("is_work"):
            return True
        async with sqlalchemy_client.session_factory() as session:
            bot_id = await redis_client.get("bot_id")
            r = await session.scalar(select(Bot.is_started).where(Bot.id == bot_id))
            await redis_client.save("is_work", r, ttl)
            return r
