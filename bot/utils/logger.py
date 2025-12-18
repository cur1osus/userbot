import datetime
import logging
import sys

try:  # Используем timezone базы системы, иначе фиксированный сдвиг
    from zoneinfo import ZoneInfo

    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    MOSCOW_TZ = datetime.timezone(datetime.timedelta(hours=3))


def setup_logger() -> None:
    """Настройка логирования для приложения."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("schedule").setLevel(logging.WARNING)
    # Формат логов
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    formatter.converter = lambda timestamp: datetime.datetime.fromtimestamp(timestamp, MOSCOW_TZ).timetuple()

    # Обработчик для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
