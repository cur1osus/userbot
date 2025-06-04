from db.sqlalchemy.models import MessageToAnswer
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813
from db.redis.redis_client import RedisClient


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    # logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^answer"))
    async def handle_answer(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = (await client.get_me()).id
            args = fn.parse_command(event.message.message, sep="\n")
            messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
            for message_to_answer in args:
                if message_to_answer in messages_to_answer:
                    await client.send_message(
                        entity=me,
                        message=f"Ответ '{message_to_answer}' уже есть, он не будет добавлен",
                    )
                    continue
                await session.execute(insert(MessageToAnswer).values(sentence=message_to_answer))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Ответы добавлены.",
                reply_to=event.message,
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all answer$"))
    async def handle_all_answer(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
        response = (
            fn.collect_in_text(
                iter_=messages_to_answer,
                func=fn.markdown_code_style,
                sep="\n\n",
            )
            if messages_to_answer
            else "Нет ответов"
        )
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unanswer"))
    async def handle_unanswer(event: events.NewMessage.Event) -> None:
        async with sessionmaker() as session:
            me = (await client.get_me()).id
            counter_del = 0
            args = fn.parse_command(event.message.message, sep="\n")
            messages_to_answer = await fn.get_messages_to_answer(sqlalchemy_client)
            for message_to_answer in args:
                if message_to_answer not in messages_to_answer:
                    await client.send_message(
                        entity=me,
                        message=f"Ответ '{message_to_answer}' не существует, он не может быть удален",
                    )
                    continue
                counter_del += 1
                await session.execute(delete(MessageToAnswer).where(MessageToAnswer.sentence == message_to_answer))
            await session.commit()
            if not counter_del:
                return
            await client.send_message(
                entity=me,
                message="Ответы удалены",
                reply_to=event.message,
            )
