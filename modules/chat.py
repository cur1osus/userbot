from db.sqlalchemy.models import MonitoringChat
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^chat"))
    async def handle_chat(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            args = fn.parse_command(event.message.message)
            monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
            for chat_id in args:
                if int(chat_id) in monitoring_chat:
                    continue
                await session.execute(insert(MonitoringChat).values(id_chat=int(chat_id)))
            await session.commit()
            await client.send_message(entity=me, message="Чат(-ы) добавлены", reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all chat$"))
    async def handle_all_chat(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
        response = ", ".join([str(chat_id) for chat_id in monitoring_chat]) if monitoring_chat else "Нет чатов"
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unchat"))
    async def handle_unchat(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            args = fn.parse_command(event.message.message)
            monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
            for chat_id in args:
                if int(chat_id) not in monitoring_chat:
                    continue
                await session.execute(delete(MonitoringChat).where(MonitoringChat.id_chat == int(chat_id)))
            await session.commit()
            await client.send_message(entity=me, message="Чат(-ы) удалены", reply_to=event.message)
