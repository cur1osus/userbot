import logging
import sys


def setup_logger() -> None:
    """Настройка логирования для приложения."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("schedule").setLevel(logging.WARNING)
    # Формат логов
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Обработчик для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
