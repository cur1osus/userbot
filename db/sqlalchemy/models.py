from sqlalchemy import (
    BigInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MonitoringChat(Base):
    __tablename__ = "monitoring_chats"

    id_chat: Mapped[str] = mapped_column(String(50), unique=True)


class Keyword(Base):
    __tablename__ = "keywords"

    word: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class IgnoredWord(Base):
    __tablename__ = "ignored_words"

    word: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class MessageToAnswer(Base):
    __tablename__ = "messages_to_answer"

    sentence: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)


class BannedUser(Base):
    __tablename__ = "banned_users"

    username: Mapped[str] = mapped_column(String(50), nullable=True)
    is_banned: Mapped[bool] = mapped_column(default=False)


class User(Base):
    __tablename__ = "users"

    id_user: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(50), nullable=True)
    message_id: Mapped[str] = mapped_column(String(50), nullable=True)
    chat_id: Mapped[str] = mapped_column(String(50), nullable=True)
    sended: Mapped[bool] = mapped_column(default=False)
