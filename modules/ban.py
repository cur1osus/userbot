import logging

from db.redis.redis_client import RedisClient
from db.sqlalchemy.models import BannedUser
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from sqlalchemy import delete, insert, update
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, sqlalchemy_client: SQLAlchemyClient, redis_client: RedisClient) -> None:
    logger = logging.getLogger(__name__)
    sessionmaker = sqlalchemy_client.session_factory

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^ban"))
    async def handle_ban(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        async with sessionmaker() as session:
            args = fn.parse_command(event.message.message)
            banned_usernames = await fn.get_banned_usernames(sqlalchemy_client)
            for username in args:
                if username in banned_usernames:
                    continue
                await session.execute(insert(BannedUser).values(username=username))
            await session.commit()
            await client.send_message(
                entity=me,
                message="Пользователь(-и) забанены",
                reply_to=event.message,
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^all ban$"))
    async def handle_all_ban(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        banned_usernames = await fn.get_banned_usernames(sqlalchemy_client)
        response = ", ".join(banned_usernames) if banned_usernames else "Нет забаненных пользователей"
        await client.send_message(entity=me, message=response, reply_to=event.message)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^unban"))
    async def handle_unban(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        async with sessionmaker() as session:
            args = fn.parse_command(event.message.message)
            banned_usernames = await fn.get_banned_usernames(sqlalchemy_client)
            for username in args:
                if username not in banned_usernames:
                    continue
                await session.execute(delete(BannedUser).where(BannedUser.username == username))
                try:
                    entity = await client.get_entity(username)
                except ValueError:
                    continue
                await fn.unblock_user(client, entity)
            await session.commit()
            await client.send_message(
                entity=me,
                message="Пользователь(-и) разбанены",
                reply_to=event.message,
            )

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^block$"))
    async def handle_block(event: events.NewMessage.Event) -> None:
        me = (await client.get_me()).id
        async with sessionmaker() as session:
            not_banned_usernames = await fn.get_not_banned_usernames(sqlalchemy_client)
            for user in not_banned_usernames:
                try:
                    user_entity = await client.get_entity(user)
                    await fn.block_user(client, user_entity)
                    await session.execute(
                        update(BannedUser)
                        .where(BannedUser.username == f"@{user_entity.username}")
                        .values(is_banned=True),
                    )
                except Exception as e:
                    logger.exception(f"Error blocking user {user}: {e}")
                    continue
            await session.commit()
            await client.send_message(
                entity=me,
                message="Пользователь(-и) заблокированы",
                reply_to=event.message,
            )
