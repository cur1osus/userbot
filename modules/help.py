from db.redis.redis_client import RedisClient
from telethon import TelegramClient, events
from utils.func import Function as fn  # noqa: N813


def register(client: TelegramClient, redis_client: RedisClient) -> None:
    """Регистрация команды update."""
    # logger = logging.getLogger(__name__)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^help$"))
    async def handle_help(event: events.NewMessage.Event) -> None:
        me = await fn.get_me_cashed(client, redis_client)
        await client.send_message(
            entity=me,
            message="""
Доступные команды:

`start` - начать отправку

`stop` - остановить отправку

`ban` <username1>, <username2>, ... 
- заблокировать пользователя(-ов)

`unban` <username1>, <username2>, ... 
- разблокировать пользователя(-ов)

`all ban` - список заблокированных пользователей

`keyword` <keyword1>, <keyword2>, ... 
- добавить триггерные слова

`all keyword` - список триггерных слов

`unkeyword` <keyword1>, <keyword2>, ... 
- удалить триггерные слова

`ignore` <word1>, <word2>, ... 
- добавить игнорируемые слова

`all ignore` - список игнорируемых слов

`unignore` <word1>, <word2>, ... 
- удалить игнорируемые слова

`answer` <sentence1>, <sentence2>, ... 
- добавить предложения для ответа

`all answer` - список предложений для ответа

`unanswer` <sentence1>, <sentence2>, ... 
- удалить предложения для ответа

`chat` <id1>, <id2>, ...
- добавить id для отслеживания

`all chat` - список id отслеживаемых чатов и каналов

`unchat` - удалить id из отслеживаемых чатов и каналов

`block` - заблокировать всех не заблокированных пользователей

`help` - список команд
            """,
            reply_to=event.message,
        )
