import logging

from telethon import TelegramClient, events


def register(client: TelegramClient, *args, **kwargs):
    """Регистрация команды id."""
    logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.id$"))
    async def get_id(event):
        """Обработчик команды .id."""
        try:
            if event.is_reply:
                message = await event.get_reply_message()
                user = await message.get_sender()
                chat = await event.get_chat()
                response = (
                    f"**ID пользователя**: {user.id}\n"
                    f"**Имя пользователя**: {user.first_name or 'N/A'}\n"
                    f"**ID чата**: {chat.id}\n"
                    f"**Название чата**: {getattr(chat, 'title', 'N/A')}"
                )
            else:
                chat = await event.get_chat()
                response = f"**ID чата**: {chat.id}\n**Название чата**: {getattr(chat, 'title', 'N/A')}"
            await event.edit(response)
            logger.info(f"Команда id выполнена для чата {chat.id}")
        except Exception as e:
            await event.edit(f"Ошибка: {e}")
            logger.error(f"Ошибка в команде id: {e}")
