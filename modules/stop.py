import logging

from db.redis.redis_client import RedisClient
from telethon import TelegramClient, events
from utils.func import Function as fn


def register(client: TelegramClient, redis_client: RedisClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^stop$"))
    async def stop(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        try:
            await redis_client.save(key="work", value=False)
            await client.send_message(entity=me, message="Остановил работу", reply_to=event.message)
        except Exception as e:
            logger.exception(f"Error in handle_stop: {e}")
            await client.send_message(entity=me, message=f"Ошибка: {e!s}", reply_to=event.message)
