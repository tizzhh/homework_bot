import logging
import os
import sys
import time
from contextlib import suppress
from functools import wraps
from http import HTTPStatus
from logging import StreamHandler
from typing import Union

import requests
import telegram
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = StreamHandler(stream=sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] @%(funcName)s: line %(lineno)d %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

EXPECTED_TOKENS = (
    'PRACTICUM_TOKEN',
    'TELEGRAM_TOKEN',
    'TELEGRAM_CHAT_ID',
)

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}


def check_tokens() -> None:
    """Функция для проверки наличия обязательных переменных окружения."""
    if missing_tokens := [
        token for token in EXPECTED_TOKENS if not globals()[token]
    ]:
        message = (
            f'Отсутствие обязательных переменных '
            f'окружения: {" ".join(missing_tokens)}'
        )
        logger.critical(message)
        sys.exit(message)


def logger_debug(func):
    """Декоратор для логирования уровня DEBUG."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(
            f'Начало выполнения {func.__name__}'
            f'с args: {args}, kwargs: {kwargs}'
        )
        output = func(*args, **kwargs)
        logger.debug(
            f'Конец выполнения {func.__name__}' f'с args: {args}, {kwargs}'
        )
        return output

    return wrapper


def was_this_message_already_sent(func):
    """Декоратор для проверки последнего отправленного сообщения."""
    last_msg = ''

    @wraps(func)
    def wrapper(bot, message):
        nonlocal last_msg
        if message != last_msg:
            last_msg = message
            return func(bot, message)
        logger.debug(f'Было получено повторяющееся сообщение: {message}')

    return wrapper


@was_this_message_already_sent
@logger_debug
def send_message(bot: telegram.Bot, message: str) -> None:
    """Функиця для отправки ботом сообщения."""
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)


@logger_debug
def get_api_answer(
        timestamp: int,
) -> dict[str, Union[list[dict[str, Union[str, int]]], int]]:
    """Функция для получения ответа от API."""
    try:
        response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )
    except requests.RequestException as error:
        raise ConnectionError(f'Ошибка при попытке запроса к API: {error}')

    if response.status_code != HTTPStatus.OK:
        raise ValueError(
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )
    return response.json()


@logger_debug
def check_response(response: requests.Response) -> None:
    """Функция для проверки наличия необходимых ключей в ответе."""
    if not isinstance(response, dict):
        raise TypeError(f'API вернул не словарь, а {type(response)}')
    if 'homeworks' not in response:
        raise KeyError('отсутствие ключа homeworks в ответе API')
    if not isinstance(response['homeworks'], list):
        raise TypeError(
            f'Под ключом homeworks находится не список,'
            f'а {type(response["homeworks"])}'
        )


@logger_debug
def parse_status(homework: dict[str, Union[int, str]]) -> str:
    """Функция для парсинга статуса проверки домашней работы."""
    if 'homework_name' not in homework:
        raise KeyError('Отсутствие ключа homework_name в ответе API')
    if 'status' not in homework:
        raise KeyError('Отсутствие ключа status в ответе API')
    recieved_status = homework['status']
    if recieved_status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неожиданный статус домашки: {recieved_status}')
    return (
        f'Изменился статус проверки работы "{homework["homework_name"]}".'
        f'{HOMEWORK_VERDICTS[homework["status"]]}'
    )


def main() -> None:
    """Основная логика работы бота."""
    check_tokens()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    while True:
        try:
            response = get_api_answer(timestamp - RETRY_PERIOD)
            check_response(response)
            homeworks = response['homeworks']
            if not homeworks:
                logger.info('Обновления отсутствуют')
                continue
            message = parse_status(response['homeworks'][0])
            send_message(bot, message)
            timestamp = response.get('current_date', timestamp)
        except telegram.error.TelegramError as error:
            logger.error(f'Сбой в работе телеграмма: {error}')
        except Exception as error:
            error_msg = f'Сбой в работе программы: {error}'
            logger.error(error_msg, exc_info=True)
            with suppress(telegram.error.TelegramError):
                send_message(bot, error_msg)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
