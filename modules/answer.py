from db.sqlalchemy.models import MessageToAnswer
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^answer"))
    async def handle_answer(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            message = event.message.message.split(" ", 1)[1]
            args = [r.strip() for r in message.split("\n") if r]
            messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
            for message_to_answer in args:
                if message_to_answer in messages_to_answer:
                    continue
                await session.execute(insert(MessageToAnswer).values(sentence=message_to_answer))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Ответы добавлены",
                reply_to=event.message,
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all answer$"))
    async def handle_all_answer(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
        response = "\n\n".join(messages_to_answer) if messages_to_answer else "Нет ответов"
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unanswer"))
    async def handle_unanswer(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = await client.get_me()
            args = fn.parse_command(event.message.message)
            messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
            for message_to_answer in args:
                if message_to_answer not in messages_to_answer:
                    continue
                await session.execute(delete(MessageToAnswer).where(MessageToAnswer.sentence == message_to_answer))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Ответы удалены",
                reply_to=event.message,
            )
