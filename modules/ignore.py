from db.sqlalchemy.models import IgnoredWord
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^ignore"))
    async def handle_ignore(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            args = fn.parse_command(event.message.message)
            ignored_words = await fn.get_ignored_words(sqlalchemy_client)
            for ignored_word in args:
                if ignored_word in ignored_words:
                    continue
                await session.execute(insert(IgnoredWord).values(word=ignored_word))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Игнорируемые слова добавлены",
                reply_to=event.message,
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all ignore$"))
    async def handle_all_ignore(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        ignored_words = await fn.get_ignored_words(sqlalchemy_client)
        response = ", ".join(ignored_words) if ignored_words else "Нет игнорируемых слов"
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unignore"))
    async def handle_unignore(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            args = fn.parse_command(event.message.message)
            ignored_words = await fn.get_ignored_words(sqlalchemy_client)
            for ignored_word in args:
                if ignored_word not in ignored_words:
                    continue
                await session.execute(delete(IgnoredWord).where(IgnoredWord.word == ignored_word))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Игнорируемые слова удалены",
                reply_to=event.message,
            )
