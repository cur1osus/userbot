from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import Keyword
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^keyword"))
    async def handle_keyword(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await fn.get_me_cashed(client, redis_client)
            args = fn.parse_command(event.message.message)
            keywords = await fn.get_keywords(sqlalchemy_client, redis_client)
            for keyword in args:
                if keyword in keywords:
                    continue
                await session.execute(insert(Keyword).values(word=keyword))
            await session.commit()
            await client.send_message(entity=me, message="Триггерные слова добавлены", reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all keyword$"))
    async def handle_all_keyword(event: events.NewMessage.Event) -> None:
        me = await fn.get_me_cashed(client, redis_client)
        keywords = await fn.get_keywords(sqlalchemy_client, redis_client)
        response = ", ".join(keywords) if keywords else "Нет триггерных слов"
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unkeyword"))
    async def handle_unkeyword(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await fn.get_me_cashed(client, redis_client)
            args = fn.parse_command(event.message.message)
            keywords = await fn.get_keywords(sqlalchemy_client, redis_client)
            for keyword in args:
                if keyword not in keywords:
                    continue
                await session.execute(delete(Keyword).where(Keyword.word == keyword))
            await session.commit()
            await client.send_message(entity=me, message="Триггерные слова удалены", reply_to=event.message)
