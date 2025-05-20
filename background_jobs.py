import datetime
import logging
from typing import Any

from db.redis.redis_client import RedisClient
from db.sqlalchemy.sqlalchemy_client import SQLAlchemyClient
from utils.func import Function as fn  # noqa: N813

logger = logging.getLogger(__name__)


# async def send_daily_report(client: TelegramClient):
#     """Отправка ежедневного отчета в 'Избранное'."""
#     try:
#         await client.send_message("me", "Ежедневный отчет")
#         logger.info("Ежедневный отчет отправлен")
#     except Exception as e:
#         logger.error(f"Ошибка при отправке отчета: {e}")


# async def cleanup_database(sqlalchemy_client: SQLAlchemyClient):
#     """Очистка старых записей в базе данных."""
#     try:
#         async with sqlalchemy_client.session_factory() as session:
#             # Пример: удаление записей старше 7 дней (нужна дополнительная колонка с датой)
#             logger.info("Очистка базы данных выполнена")
#     except Exception as e:
#         logger.error(f"Ошибка при очистке базы данных: {e}")


async def send_message(client: Any, redis_client: RedisClient, sqlalchemy_client: SQLAlchemyClient) -> None:
    if datetime.datetime.now().second % 20 == 0:  # noqa: DTZ005
        if not await redis_client.get("work"):
            logger.info("Отправка сообщения остановлена")
            return
        user = await fn.get_closer_data_user(sqlalchemy_client)
        if not user:
            logger.info("Нет пользователей для отправки сообщений")
            return
        ans = await fn.take_message_answer(redis_client, sqlalchemy_client)
        try:
            await client.send_message(entity=user.id_user, message=ans)
            await client.forward_messages(
                entity=user.id_user,
                messages=int(user.message_id),
                from_peer=int(user.chat_id),
            )

            logger.info(f"Сообщение было отправлено успешно {user.id_user}, {user.username}")
        except Exception as e:
            logger.info(f"Произошла ошибка при отправке сообщения: {e.with_traceback}\n")
