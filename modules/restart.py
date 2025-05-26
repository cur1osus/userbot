import logging
import os
import sys

from telethon import TelegramClient, events


def register(client: TelegramClient, *args, **kwargs) -> None:
    """Регистрация команды restart."""
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.restart$"))
    async def restart(event: events.NewMessage.Event) -> None:
        """Обработчик команды .restart."""
        try:
            await event.edit("Перезапуск...")
            logger.info("Инициирован перезапуск бота")
            os.execv(sys.executable, [sys.executable, *sys.argv])  # noqa: S606
        except Exception as e:
            await event.edit(f"Ошибка при перезапуске: {e}")
            logger.exception(f"Ошибка в команде restart: {e}")
