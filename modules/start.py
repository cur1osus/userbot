import logging

from db.redis.redis_client import RedisClient
from telethon import TelegramClient, events


def register(client: TelegramClient, redis_client: RedisClient) -> None:
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^start$"))
    async def start(event: events.NewMessage.Event) -> None:
        try:
            me = await client.get_me()
            await redis_client.save(key="work", value=True)
            await client.send_message(entity=me, message="Начал работать", reply_to=event.message)
        except Exception as e:
            logger.exception(f"Error in handle_start: {e}")
            await client.send_message(entity=me, message=f"Ошибка: {e!s}", reply_to=event.message)
