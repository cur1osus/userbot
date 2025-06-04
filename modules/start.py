import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^start$"))
    async def start(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        me_cashed = (await client.get_me()).id
        if me.id != me_cashed:
            await redis_client.save(key="me", value=me.id)
            await fn.reset_users_sended_status(sqlalchemy_client)
            logger.info("Сбросил статус отправки у users")
        try:
            await redis_client.save(key="work", value=True)
            await client.send_message(entity=me, message="Начал работать", reply_to=event.message)
        except Exception as e:
            logger.exception(f"Error in handle_start: {e}")
            await client.send_message(entity=me, message=f"Ошибка: {e!s}", reply_to=event.message)
