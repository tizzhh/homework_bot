class MissingKeyInAPIResponse(Exception):
    """Класс исключения неправильного ответа от API."""

    ...


class UnexpectedResponseCode(Exception):
    """Класс исключения кода ответа, не равному 200."""

    ...


class EmptyHomeworks(Exception):
    """Класс исключения пустого списка домашек."""

    ...
