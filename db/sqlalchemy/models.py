from sqlalchemy import (
    BigInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MonitoringChat(Base):
    __tablename__ = "monitoring_chats"

    bot_id: Mapped[int] = mapped_column()
    id_chat: Mapped[str] = mapped_column(String(50))


class KeyWord(Base):
    __tablename__ = "keywords"

    word: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)


class IgnoredWord(Base):
    __tablename__ = "ignored_words"

    word: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)


class MessageToAnswer(Base):
    __tablename__ = "messages_to_answer"

    sentence: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)


class BannedUser(Base):
    __tablename__ = "banned_users"

    id_user: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(50), nullable=True)
    is_banned: Mapped[bool] = mapped_column(default=False)


class UserAnalyzed(Base):
    __tablename__ = "users_analyzed"

    id_user: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(50), nullable=True)
    message_id: Mapped[str] = mapped_column(String(50), nullable=True)
    chat_id: Mapped[str] = mapped_column(String(50), nullable=True)
    additional_message: Mapped[str] = mapped_column(String(1000))
    sended: Mapped[bool] = mapped_column(default=False)


class UserManager(Base):
    __tablename__ = "user_managers"

    id_user: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(50), nullable=True)
    users_per_minute: Mapped[int] = mapped_column(default=1)


class Bot(Base):
    __tablename__ = "bots"

    name: Mapped[str] = mapped_column(String(50), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), unique=True)
    api_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    api_hash: Mapped[str] = mapped_column(String(100))
    path_session: Mapped[str] = mapped_column(String(100))
    is_started: Mapped[bool] = mapped_column(default=False)
