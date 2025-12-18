"""
Модуль для управления алиасами команд
Содержит словарь соответствий русских команд английским
"""

# Словарь алиасов: русская_команда -> английская_команда
COMMAND_ALIASES = {
    # Статистика и топ
    "стата": "top",
    "топ": "top",
    "стата вся": "topall",
    "статистика вся": "topall",
    
    # Профиль
    "профиль": "myprofile",
    "мой профиль": "myprofile",
    "кто ты": "myprofile",
    
    # Настройки
    "настройки": "settings",
    "конфиг": "settings",
    
    # Модерация
    "мут": "mute",
    "размут": "unmute",
    "кик": "kick",
    "бан": "ban",
    "разбан": "unban",
    "варн": "warn",
    "анварн": "unwarn",
    "голос мут": "votemute",
    "голосование": "votemute",

    # Ранги/модераторы (alias к /ap и /unap)
    "назначить": "ap",
    "снять": "unap",
    "remove": "unap",

    # Служебное
    "кто админ": "staff",
    
    # Защита от рейдов
    "антирейд": "raidprotection",
    "настройки антирейд": "raidprotection",
}

def get_command_alias(text: str) -> str | None:
    """
    Получить английскую команду по русскому алиасу
    
    Args:
        text: Текст сообщения
        
    Returns:
        Английская команда или None если алиас не найден
    """
    # Убираем лишние пробелы и приводим к нижнему регистру
    clean_text = text.strip().lower()
    
    # Специальная обработка для команды "кто я" - всегда без аргументов
    if clean_text == "кто я":
        return "myprofile_self"
    # Специальная обработка для само-снятия
    if clean_text == "снять меня":
        return "selfdemote"
    
    # Проверяем точное совпадение (команда без аргументов)
    if clean_text in COMMAND_ALIASES:
        return COMMAND_ALIASES[clean_text]
    
    # Специальная проверка для команды "кто ты" с аргументами
    if clean_text.startswith("кто ты"):
        return "myprofile"
    
    # Проверяем команду с аргументами (первое слово должно быть алиасом)
    words = clean_text.split()
    if words and words[0] in COMMAND_ALIASES:
        return COMMAND_ALIASES[words[0]]
    
    return None

def is_command_alias(text: str) -> bool:
    """
    Проверить, является ли текст алиасом команды
    
    Args:
        text: Текст сообщения
        
    Returns:
        True если это алиас команды, False иначе
    """
    # Проверяем на None и пустую строку
    if not text or text is None:
        return False
    
    # Убираем лишние пробелы и приводим к нижнему регистру
    clean_text = text.strip().lower()
    
    # Специальная обработка для команды "кто я"
    if clean_text == "кто я":
        return True
    # Специальная обработка для само-снятия
    if clean_text == "снять меня":
        return True
    
    # Проверяем точное совпадение (команда без аргументов)
    if clean_text in COMMAND_ALIASES:
        return True
    
    # Специальная проверка для команды "кто ты" с аргументами
    if clean_text.startswith("кто ты"):
        return True
    
    # Проверяем команду с аргументами (первое слово должно быть алиасом)
    words = clean_text.split()
    if words and words[0] in COMMAND_ALIASES:
        return True
    
    # Проверяем команду с префиксом "пиксель"
    if clean_text.startswith("пиксель"):
        # Убираем префикс и проверяем остальную часть
        text_without_prefix = clean_text[7:].strip()  # "пиксель" = 7 символов
        
        # Проверяем точное совпадение без префикса
        if text_without_prefix in COMMAND_ALIASES or text_without_prefix == "снять меня":
            return True
        
        # Проверяем команду с аргументами без префикса
        words_without_prefix = text_without_prefix.split()
        if words_without_prefix and words_without_prefix[0] in COMMAND_ALIASES:
            return True
    
    return False

def get_all_aliases() -> dict[str, str]:
    """
    Получить все алиасы команд
    
    Returns:
        Словарь всех алиасов
    """
    return COMMAND_ALIASES.copy()

def add_alias(russian_command: str, english_command: str) -> None:
    """
    Добавить новый алиас команды
    
    Args:
        russian_command: Русская команда
        english_command: Английская команда
    """
    COMMAND_ALIASES[russian_command.lower()] = english_command.lower()

def remove_alias(russian_command: str) -> bool:
    """
    Удалить алиас команды
    
    Args:
        russian_command: Русская команда для удаления
        
    Returns:
        True если алиас был удален, False если не найден
    """
    if russian_command.lower() in COMMAND_ALIASES:
        del COMMAND_ALIASES[russian_command.lower()]
        return True
    return False
