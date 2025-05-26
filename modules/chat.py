from db.sqlalchemy.models import MonitoringChat
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813
from db.redis.redis_client import RedisClient


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^chat"))
    async def handle_chat(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await fn.get_me_cashed(client, redis_client)
            args = fn.parse_command(event.message.message)
            monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
            for chat_id in args:
                if chat_id in monitoring_chat:
                    await client.send_message(entity=me, message=f"Чат {chat_id} уже был ранее добавлен")
                    continue
                await session.execute(insert(MonitoringChat).values(id_chat=int(chat_id)))
            await session.commit()
            await client.send_message(entity=me, message="Чат(-ы) добавлены", reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all chat$"))
    async def handle_all_chat(event: events.NewMessage.Event) -> None:
        me = await fn.get_me_cashed(client, redis_client)
        monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
        response = (
            fn.collect_in_text(
                iter_=monitoring_chat,
                func=fn.markdown_code_style,
                sep="\n",
            )
            if monitoring_chat
            else "Нет чатов"
        )
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unchat"))
    async def handle_unchat(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await fn.get_me_cashed(client, redis_client)
            counter_del = 0
            args = fn.parse_command(event.message.message)
            monitoring_chat = await fn.get_monitoring_chat(sqlalchemy_client)
            for chat_id in args:
                if chat_id not in monitoring_chat:
                    await client.send_message(
                        entity=me,
                        message=f"Чат {chat_id} не существует в Базе",
                    )
                    continue
                counter_del += 1
                await session.execute(delete(MonitoringChat).where(MonitoringChat.id_chat == int(chat_id)))
            await session.commit()
            if not counter_del:
                return
            await client.send_message(entity=me, message="Чат(-ы) удалены", reply_to=event.message)
