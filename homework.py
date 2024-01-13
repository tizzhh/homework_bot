import logging
import os
import sys
import time
from logging import StreamHandler
from typing import Union

import requests
import telegram
from dotenv import load_dotenv

from modules.exceptions import (
    EmptyHomeworks,
    MissingKeyInAPIResponse,
    UnexpectedResponseCode,
)

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = StreamHandler(stream=sys.stdout)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

EXPECTED_HOMEWORK_KEYS = set(
    [
        'id',
        'status',
        'homework_name',
        'reviewer_comment',
        'date_updated',
        'lesson_name',
    ]
)

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}


def check_tokens() -> bool:
    """Функция для проверки наличия обязательных переменных окружения."""
    return PRACTICUM_TOKEN and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID


def send_message(bot: telegram.Bot, message: str) -> None:
    """Функиця для отправки ботом сообщения."""
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.debug(
            f'Отправлено сообщение юзеру {TELEGRAM_CHAT_ID} '
            f'с текстом {message}'
        )
    except telegram.error.TelegramError as error:
        logger.error(
            f'Отправка сообщения юзеру {TELEGRAM_CHAT_ID} '
            f'с текстом {message} вызвало ошибку: {error}'
        )


def get_api_answer(timestamp: int) -> requests.Response:
    """Функция для получения ответа от API."""
    try:
        response: requests.Response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )
    except requests.RequestException as error:
        logger.error(f'Ошибка при попытке запроса к API: {error}')

    if response.status_code != 200:
        raise UnexpectedResponseCode(
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )

    return response.json()


def check_response(response: requests.Response) -> None:
    """Функция для проверки наличия необходимых ключей в ответе."""
    if not isinstance(response, dict):
        raise TypeError(f'API вернул не словарь, а {type(response)}')
    elif 'homeworks' not in response or 'current_date' not in response:
        raise MissingKeyInAPIResponse(
            'отсутствие ожидаемых ключей в ответе API'
        )
    elif not isinstance(response['homeworks'], list):
        raise TypeError(
            f'Под ключом homeworks находится не список,'
            f'а {type(response["homeworks"])}'
        )
    elif len(response['homeworks']) == 0:
        raise EmptyHomeworks('Нет домашек новых!')
    elif not isinstance(response['homeworks'][0], dict):
        raise TypeError(
            f'В списке homeworks лежат не словари, '
            f'а {type(response["homeworks"][0])}'
        )
    elif set(response['homeworks'][0]) > set(EXPECTED_HOMEWORK_KEYS):
        raise MissingKeyInAPIResponse(
            'отсутствие ожидаемых ключей в ключе ответа homeworks'
        )


def parse_status(homework: dict[str, Union[int, str]]) -> str:
    """Функция для парсинга статуса проверки домашней работы."""
    try:
        homework_name = homework['homework_name']
    except KeyError as error:
        logger.error(f'Отсутствие ключа homework_name в ответе API: {error}')

    try:
        status = homework['status']
    except KeyError as error:
        logger.error(f'Отсутствие ключа status в ответе API: {error}')

    try:
        verdict = HOMEWORK_VERDICTS[status]
    except KeyError as error:
        logging.error(f'Неожиданный статус домашки: {error}')

    return f'Изменился статус проверки работы "{homework_name}".' f'{verdict}'


def main() -> None:
    """Основная логика работы бота."""
    if not check_tokens():
        logger.critical('Отсутствие обязательных переменных окружения')
        return

    # Не уверен, что на эти две переменные нужно добавлять аннотации,
    # потому что вроде бы и так понятно, а
    # bot: telegram.Bot = telegram.Bot(...) выглядит странно...?
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())

    while True:
        try:
            response: requests.Response = get_api_answer(
                timestamp - RETRY_PERIOD
            )
            check_response(response)
            status: str = parse_status(response['homeworks'][0])
            send_message(bot, status)
            timestamp = response['current_date']
        except MissingKeyInAPIResponse as error:
            logger.error(f'Неверный ответ от API: {error}')
            send_message(bot, str(error))
        except Exception as error:
            logger.error(f'Сбой в работе программы: {error}')
            send_message(bot, str(error))

        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
