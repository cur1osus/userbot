import logging
import time

from telethon import TelegramClient, events


def register(client: TelegramClient, *args, **kwargs):
    """Регистрация команды ping."""
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.ping$"))
    async def ping(event):
        """Обработчик команды .ping."""
        try:
            start = time.time()
            await event.edit("Pong!")
            end = time.time()
            response_time = (end - start) * 1000
            await event.edit(f"Pong! 🏓\nВремя ответа: {response_time:.2f} мс")
            logger.info(f"Команда ping выполнена, время ответа: {response_time:.2f} мс")  # noqa: G004
        except Exception as e:
            await event.edit(f"Ошибка: {e}")
            logger.exception(f"Ошибка в команде ping: {e}")  # noqa: G004, TRY401
