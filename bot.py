"""
Telegram бот Pixel Utils Bot - чат менеджер

Copyright (c) 2025 GlebSoloProjects

This project is licensed under MIT License.
See LICENSE file for details.

ATTRIBUTION REQUIREMENT:
If you modify or distribute this Software, you MUST include a reference to the
original project in the source code (e.g., in README.md or in code comments).

Required attribution:
- Original Project: Pixel Utils Bot
- Creator: GlebSoloProjects
- Website: https://pixel-ut.pro
- Telegram: @pixel_ut_bot
"""
import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sqlite3
import sys
import time
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, ChatPermissions, 
    CallbackQuery, InputMediaPhoto, BufferedInputFile, ChatJoinRequest, ChatMemberUpdated
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, BOT_NAME, BOT_DESCRIPTION, DEBUG, TIMEZONE_DB_PATH, TOP_CHATS_DEFAULTS
from database import db
from moderation_db import moderation_db
from reputation_db import reputation_db
from timezone_db import TimezoneDatabase
from scheduler import TaskScheduler
from command_aliases import get_command_alias, is_command_alias
from image_generator import generate_modern_profile_card, generate_top_chart, generate_activity_chart
from network_db import network_db
from votemute_db import votemute_db
from friends_db import friends_db
from raid_protection_db import raid_protection_db
from raid_protection import raid_protection
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, Tuple, List, Dict, Any

# Обработчик заявок на вступление добавляется после инициализации dp ниже
# Ранги модерации
RANK_OWNER = 1
RANK_ADMIN = 2
RANK_SENIOR_MOD = 3
RANK_JUNIOR_MOD = 4
RANK_USER = 5

RANK_NAMES = {
    1: ("Владелец", "Владельцы"),
    2: ("Администратор", "Администраторы"),
    3: ("Старший модератор", "Старшие модераторы"),
    4: ("Младший модератор", "Младшие модераторы"),
    5: ("Пользователь", "Пользователи")
}

# Дефолтная конфигурация прав для рангов
DEFAULT_RANK_PERMISSIONS = {
    1: {  # Владелец - все права
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': True, 'can_assign_rank_3': True,
        'can_assign_rank_2': True, 'can_remove_rank': True,
        'can_config_warns': True, 'can_config_ranks': True,
        'can_view_stats': True
    },
    2: {  # Администратор - настройки и назначение
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': True, 'can_assign_rank_3': True,
        'can_assign_rank_2': False, 'can_remove_rank': True,
        'can_config_warns': True, 'can_config_ranks': True,
        'can_view_stats': True
    },
    3: {  # Старший модератор - баны и кики
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': True, 'can_ban': True, 'can_unban': True,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_view_stats': True
    },
    4: {  # Младший модератор - варны и муты
        'can_warn': True, 'can_unwarn': True,
        'can_mute': True, 'can_unmute': True,
        'can_kick': False, 'can_ban': False, 'can_unban': False,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_view_stats': True
    },
    5: {  # Пользователь - нет прав
        'can_warn': False, 'can_unwarn': False,
        'can_mute': False, 'can_unmute': False,
        'can_kick': False, 'can_ban': False, 'can_unban': False,
        'can_assign_rank_4': False, 'can_assign_rank_3': False,
        'can_assign_rank_2': False, 'can_remove_rank': False,
        'can_config_warns': False, 'can_config_ranks': False,
        'can_view_stats': False
    }
}

def get_rank_name(rank: int, count: int = 1) -> str:
    """Получить название ранга с учетом множественного числа"""
    return RANK_NAMES[rank][0] if count == 1 else RANK_NAMES[rank][1]


def parse_mute_duration(time_str: str) -> Optional[int]:
    """
    Парсит строку времени в секунды
    Примеры: "10 часов", "30 минут", "5 дней", "60 секунд"
    Возвращает количество секунд или None при ошибке
    """
    import re
    
    # Убираем лишние пробелы и приводим к нижнему регистру
    time_str = time_str.strip().lower()
    
    # Регулярное выражение для поиска числа и единицы времени
    pattern = r'(\d+)\s*([а-яё]+)'
    match = re.match(pattern, time_str)
    
    if not match:
        return None
    
    number = int(match.group(1))
    unit = match.group(2)
    
    # Словари для определения единиц времени (строгие совпадения)
    seconds_words = ['секунд', 'секунды', 'секунду', 'сек', 'с']
    minutes_words = ['минут', 'минуты', 'минуту', 'мин', 'м']
    hours_words = ['часов', 'часа', 'час', 'ч']
    days_words = ['дней', 'дня', 'день', 'д']
    
    # Определяем единицу времени (строгая проверка - должно быть точное совпадение)
    if unit in seconds_words:
        return number
    elif unit in minutes_words:
        return number * 60
    elif unit in hours_words:
        return number * 3600
    elif unit in days_words:
        return number * 86400
    else:
        # Неизвестная единица времени
        return None


async def get_effective_rank(chat_id: int, user_id: int) -> int:
    """
    Получить эффективный ранг пользователя:
    - Проверяет ранг в БД бота
    - Исключение: владелец чата автоматически получает ранг владельца
    - Не учитывает Telegram-статус других пользователей
    """
    try:
        # Проверяем, является ли пользователь владельцем чата
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status == 'creator':
                return RANK_OWNER  # Владелец чата всегда имеет ранг владельца
        except Exception:
            pass  # Игнорируем ошибки при проверке статуса
        
        # Проверяем ранг в БД
        db_rank = await db.get_user_rank(chat_id, user_id)
        
        # Возвращаем ранг из БД или обычного пользователя
        if db_rank is not None:
            return db_rank
        else:
            return RANK_USER  # Обычный пользователь по умолчанию
            
    except Exception as e:
        logger.error(f"Ошибка при получении ранга пользователя {user_id} в чате {chat_id}: {e}")
        # В случае ошибки возвращаем обычного пользователя
        return RANK_USER

async def check_permission(chat_id: int, user_id: int, permission_type: str, fallback_rank_check=None) -> bool:
    """
    Проверяет права с fallback на старую систему рангов
    """
    # Пытаемся получить из новой системы
    has_perm = await db.has_permission(chat_id, user_id, permission_type)
    if has_perm is not None:
        return has_perm
    
    # Fallback на старую систему
    if fallback_rank_check:
        rank = await get_effective_rank(chat_id, user_id)
        return fallback_rank_check(rank)
    
    return False


def get_user_mention_html(user, enable_link: bool = True) -> str:
    """
    Генерирует HTML-упоминание пользователя с кликабельной ссылкой на профиль
    - Для пользователей с username: использует https://t.me/username
    - Для пользователей без username: использует tg://user?id=user_id
    - Fallback: ID пользователя
    
    Принимает либо types.User объект, либо словарь с полями user_id, username, first_name
    Если enable_link=False, возвращает просто имя без ссылки
    """
    # Поддержка как User объекта, так и словаря
    if isinstance(user, dict):
        user_id = user.get('user_id')
        username = user.get('username')
        first_name = user.get('first_name', '') or ""
    else:
        user_id = user.id
        username = user.username
        first_name = user.first_name or ""
    
    # Определяем отображаемое имя
    if first_name:
        display_name = first_name
    elif username:
        display_name = username
    else:
        display_name = f"ID{user_id}"
    
    # Если ссылки отключены, возвращаем просто имя
    if not enable_link:
        return display_name
    
    # Формируем ссылку
    if username:
        # Пользователь с username - обычная ссылка на профиль
        return f"<a href='https://t.me/{username}'>{display_name}</a>"
    elif first_name:
        # Пользователь без username - используем tg://user?id=
        return f"<a href='tg://user?id={user_id}'>{first_name}</a>"
    else:
        # Fallback - ID пользователя
        return f"<a href='tg://user?id={user_id}'>ID{user_id}</a>"


# Путь к файлу настроек гифок
GIFS_SETTINGS_PATH = Path("data/gifs_settings.json")

# Путь к файлу настроек топа чатов
TOP_CHATS_SETTINGS_PATH = Path("data/top_chats_settings.json")


def init_json_files():
    """
    Инициализация JSON-файлов настроек (создание пустых файлов если их нет)
    """
    try:
        # Создаем папку data если её нет
        GIFS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Создаем пустой JSON-файл для настроек гифок, если его нет
        if not GIFS_SETTINGS_PATH.exists():
            with open(GIFS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            logger.info("Создан файл gifs_settings.json")
        
        # Создаем пустой JSON-файл для настроек топа чатов, если его нет
        if not TOP_CHATS_SETTINGS_PATH.exists():
            with open(TOP_CHATS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            logger.info("Создан файл top_chats_settings.json")
            
    except Exception as e:
        logger.error(f"Ошибка при инициализации JSON-файлов: {e}")


def get_gifs_enabled(chat_id: int) -> bool:
    """
    Получает настройку включения гифок для чата
    
    Args:
        chat_id: ID чата
    
    Returns:
        True если гифки включены, False если выключены (по умолчанию False)
    """
    try:
        if not GIFS_SETTINGS_PATH.exists():
            return False  # По умолчанию выключены
        
        with open(GIFS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        
        # Проверяем настройку для конкретного чата
        chat_id_str = str(chat_id)
        if chat_id_str in settings:
            return settings[chat_id_str].get('enabled', False)
        
        return False  # По умолчанию выключены
        
    except Exception as e:
        logger.error(f"Ошибка при чтении настроек гифок для чата {chat_id}: {e}")
        return False  # По умолчанию выключены при ошибке


def set_gifs_enabled(chat_id: int, enabled: bool) -> bool:
    """
    Устанавливает настройку включения гифок для чата
    
    Args:
        chat_id: ID чата
        enabled: True для включения, False для выключения
    
    Returns:
        True если успешно, False при ошибке
    """
    try:
        # Создаем папку data если её нет
        GIFS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Загружаем существующие настройки
        settings = {}
        if GIFS_SETTINGS_PATH.exists():
            with open(GIFS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        # Обновляем настройку для чата
        chat_id_str = str(chat_id)
        if chat_id_str not in settings:
            settings[chat_id_str] = {}
        
        settings[chat_id_str]['enabled'] = enabled
        
        # Сохраняем обратно
        with open(GIFS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек гифок для чата {chat_id}: {e}")
        return False


def get_top_chat_settings(chat_id: int) -> dict:
    """
    Получает настройки показа в топе для чата
    
    Args:
        chat_id: ID чата
    
    Returns:
        Словарь с настройками:
        - show_in_top: "always" | "public_only" | "never" (по умолчанию "public_only")
        - show_private_label: bool (по умолчанию False)
        - min_activity_threshold: int (по умолчанию 0)
    """
    try:
        # Используем дефолтные значения из config
        defaults = TOP_CHATS_DEFAULTS.copy()
        
        if not TOP_CHATS_SETTINGS_PATH.exists():
            return defaults
        
        with open(TOP_CHATS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        
        # Проверяем настройки для конкретного чата
        chat_id_str = str(chat_id)
        if chat_id_str in settings:
            chat_settings = settings[chat_id_str]
            return {
                'show_in_top': chat_settings.get('show_in_top', defaults['show_in_top']),
                'show_private_label': chat_settings.get('show_private_label', defaults['show_private_label']),
                'min_activity_threshold': chat_settings.get('min_activity_threshold', defaults['min_activity_threshold'])
            }
        
        # Возвращаем значения по умолчанию
        return defaults
        
    except Exception as e:
        logger.error(f"Ошибка при чтении настроек топа чатов для чата {chat_id}: {e}")
        return TOP_CHATS_DEFAULTS.copy()


def set_top_chat_setting(chat_id: int, setting_name: str, value) -> bool:
    """
    Устанавливает настройку показа в топе для чата
    
    Args:
        chat_id: ID чата
        setting_name: Название настройки ('show_in_top', 'show_private_label', 'min_activity_threshold')
        value: Значение настройки
    
    Returns:
        True если успешно, False при ошибке
    """
    try:
        # Создаем папку data если её нет
        TOP_CHATS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Загружаем существующие настройки
        settings = {}
        if TOP_CHATS_SETTINGS_PATH.exists():
            with open(TOP_CHATS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        # Обновляем настройку для чата
        chat_id_str = str(chat_id)
        if chat_id_str not in settings:
            settings[chat_id_str] = {}
        
        settings[chat_id_str][setting_name] = value
        
        # Сохраняем обратно
        with open(TOP_CHATS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек топа чатов для чата {chat_id}: {e}")
        return False


def get_random_gif(command_name: str) -> Optional[Tuple[BufferedInputFile, str]]:
    """
    Получает случайную гифку из папки для команды модерации
    
    Args:
        command_name: Название команды (ban, unban, mute, unmute, warn, kick, welcome)
    
    Returns:
        Кортеж (BufferedInputFile, file_type) где file_type: 'animation' или 'video', 
        или None если папка пустая/не найдена
    """
    try:
        # Путь к папке с гифками для команды
        gif_dir = Path("Gifs") / command_name
        
        # Проверяем существование папки
        if not gif_dir.exists() or not gif_dir.is_dir():
            logger.debug(f"Папка {gif_dir} не существует или не является директорией")
            return None
        
        # Поддерживаемые форматы
        animation_formats = ('.gif', '.webm')  # Форматы для answer_animation
        video_formats = ('.mp4', '.MOV', '.mov')  # Форматы для answer_video
        
        # Получаем все файлы с поддерживаемыми форматами
        all_files = [f for f in gif_dir.iterdir() 
                     if f.is_file() and f.suffix.lower() in (*animation_formats, *video_formats)]
        
        if not all_files:
            logger.debug(f"В папке {gif_dir} нет файлов с поддерживаемыми форматами")
            return None
        
        # Выбираем случайный файл
        selected_file = random.choice(all_files)
        file_ext = selected_file.suffix.lower()
        
        # Определяем тип файла
        if file_ext in animation_formats:
            file_type = 'animation'
        elif file_ext in video_formats:
            file_type = 'video'
        else:
            file_type = 'video'  # По умолчанию как видео
        
        # Читаем файл
        with open(selected_file, 'rb') as f:
            file_data = f.read()
        
        # Создаем BufferedInputFile
        file_obj = BufferedInputFile(
            file_data,
            filename=selected_file.name
        )
        
        return (file_obj, file_type)
        
    except Exception as e:
        logger.error(f"Ошибка при получении гифки для команды {command_name}: {e}")
        return None


async def send_message_with_gif(message: Message, text: str, command_name: str, parse_mode=None):
    """
    Отправляет сообщение с гифкой/видео, если оно найдено, иначе отправляет только текст
    
    Args:
        message: Объект сообщения для ответа
        text: Текст сообщения (будет использован как подпись к гифке/видео)
        command_name: Название команды для поиска гифки (ban, unban, mute, unmute, warn, kick, welcome)
        parse_mode: Режим парсинга текста (например, ParseMode.HTML)
    """
    try:
        # Проверяем настройку для чата (только для групповых чатов)
        # Исключение: приветственное сообщение (welcome) всегда отправляется с гифкой
        chat_id = message.chat.id
        if message.chat.type in ['group', 'supergroup'] and command_name != "welcome":
            gifs_enabled = get_gifs_enabled(chat_id)
            if not gifs_enabled:
                # Гифки выключены - отправляем только текст
                await message.answer(text, parse_mode=parse_mode)
                return
        
        # Пытаемся получить файл
        result = get_random_gif(command_name)
        
        if result:
            gif_file, file_type = result
            
            # Отправляем в зависимости от типа файла
            if file_type == 'animation':
                # Для .gif и .webm используем answer_animation
                await message.answer_animation(
                    animation=gif_file,
                    caption=text,
                    parse_mode=parse_mode
                )
            else:
                # Для .mp4 и .MOV используем answer_video
                await message.answer_video(
                    video=gif_file,
                    caption=text,
                    parse_mode=parse_mode
                )
        else:
            # Файл не найден - отправляем только текст
            await message.answer(text, parse_mode=parse_mode)
            
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения с гифкой/видео для команды {command_name}: {e}")
        # Fallback - отправляем только текст при ошибке
        try:
            await message.answer(text, parse_mode=parse_mode)
        except Exception as e2:
            logger.error(f"Ошибка при отправке текстового сообщения: {e2}")


async def parse_user_from_args(message: Message, args: list, arg_index: int) -> Optional[types.User]:
    """
    Извлекает информацию о пользователе из аргументов команды
    
    Поддерживает:
    1. Telegram mention entities (text_mention)
    2. @username в тексте
    3. Поиск по user_id (если аргумент - число)
    4. Поиск по first_name в текущем чате
    5. Возвращает None если не найден
    
    Args:
        message: Объект сообщения
        args: Список аргументов команды
        arg_index: Индекс аргумента для поиска
        
    Returns:
        types.User объект или None
    """
    if arg_index >= len(args):
        return None
    
    chat_id = message.chat.id
    arg = args[arg_index].strip()
    
    # Сначала проверяем entities сообщения для text_mention
    if message.entities:
        for entity in message.entities:
            if entity.type == "text_mention" and hasattr(entity, 'user'):
                # Проверяем, что это тот аргумент, который нам нужен
                # entity.offset указывает на начало упоминания
                entity_text = message.text[entity.offset:entity.offset + entity.length]
                if entity_text == arg or arg in entity_text:
                    return entity.user
    
    # Потом проверяем @username
    if arg.startswith('@'):
        username = arg[1:]
        # Ищем пользователя в базе данных
        try:
            user_data = await db.get_user_by_username(username)
            if user_data:
                # Создаем простой объект с атрибутами
                from types import SimpleNamespace
                return SimpleNamespace(
                    id=user_data['user_id'],
                    username=user_data['username'],
                    first_name=user_data['first_name'],
                    last_name=user_data.get('last_name'),
                    is_bot=user_data['is_bot']
                )
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя @{username}: {e}")
    
    # Проверяем, является ли аргумент числом (user_id)
    if arg.isdigit():
        try:
            user_id = int(arg)
            # Получаем информацию о пользователе из чата
            try:
                chat_member = await bot.get_chat_member(chat_id, user_id)
                return chat_member.user
            except Exception:
                # Пользователь не найден в чате или ошибка
                pass
        except ValueError:
            pass
    
    # Поиск по first_name в текущем чате через базу данных
    try:
        # Используем новую функцию поиска по имени в чате
        found_users = await db.search_users_by_name_in_chat(chat_id, arg)
        
        if found_users:
            # Берем первого найденного пользователя
            user_data = found_users[0]
            found_user_id = user_data['user_id']
            
            # Проверяем, что пользователь действительно в чате через Telegram API
            try:
                chat_member = await bot.get_chat_member(chat_id, found_user_id)
                return chat_member.user
            except Exception as e:
                # Пользователь не найден в чате, пробуем следующего если есть
                logger.debug(f"Пользователь {found_user_id} не найден в чате через API: {e}")
                if len(found_users) > 1:
                    # Пробуем следующего пользователя
                    for user_data in found_users[1:]:
                        try:
                            found_user_id = user_data['user_id']
                            chat_member = await bot.get_chat_member(chat_id, found_user_id)
                            return chat_member.user
                        except Exception:
                            continue
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователя по имени '{arg}': {e}")
    
    return None


async def should_show_hint(chat_id: int, user_id: int) -> bool:
    """
    Проверяет, нужно ли показывать подсказку пользователю
    """
    try:
        # Получаем режим подсказок для чата
        hints_mode = await db.get_hints_mode(chat_id)
        
        # 0 = подсказки для всех
        if hints_mode == 0:
            return True
        
        # 2 = подсказки выключены
        if hints_mode == 2:
            return False
        
        # 1 = подсказки только для модераторов
        if hints_mode == 1:
            # Проверяем ранг пользователя
            user_rank = await get_effective_rank(chat_id, user_id)
            # Показываем подсказки только модераторам (ранги 1-4)
            return user_rank <= 4
        
        return True  # По умолчанию показываем подсказки
        
    except Exception as e:
        logger.error(f"Ошибка при проверке режима подсказок: {e}")
        return True  # В случае ошибки показываем подсказки


def check_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет кулдаун пользователя
    Возвращает (can_act, remaining_seconds)
    """
    current_time = time.time()
    
    if user_id in user_cooldowns:
        last_action = user_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < COOLDOWN_DURATION:
            remaining = int(COOLDOWN_DURATION - time_passed)
            return False, remaining
    
    # Обновляем время последнего действия
    user_cooldowns[user_id] = current_time
    return True, 0


def check_timezone_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверка кулдауна для панельки часовых поясов
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in timezone_cooldowns:
        last_action = timezone_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < TIMEZONE_COOLDOWN_DURATION:
            remaining = int(TIMEZONE_COOLDOWN_DURATION - time_passed)
            return False, remaining
    
    # Обновляем время последнего действия
    timezone_cooldowns[user_id] = current_time
    return True, 0


def check_hints_config_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверка кулдауна для изменения настроек подсказок
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in hints_config_cooldowns:
        last_action = hints_config_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < HINTS_CONFIG_COOLDOWN_DURATION:
            remaining = int(HINTS_CONFIG_COOLDOWN_DURATION - time_passed)
            return False, remaining
    
    # Обновляем время последнего действия
    hints_config_cooldowns[user_id] = current_time
    return True, 0


def cleanup_old_timezone_panels():
    """Очистка старых записей владельцев панелек (вызывается периодически)"""
    # Оставляем только последние 100 записей для экономии памяти
    if len(timezone_panel_owners) > 100:
        # Удаляем самые старые записи
        items = list(timezone_panel_owners.items())
        for message_id, _ in items[:-50]:  # Оставляем 50 самых новых
            del timezone_panel_owners[message_id]


async def update_timezone_panel(callback: types.CallbackQuery, user_id: int):
    """Обновление панельки часовых поясов"""
    try:
        # Получаем текущий часовой пояс пользователя
        current_offset = await timezone_db.get_user_timezone(user_id)
        current_tz = timezone_db.format_timezone_offset(current_offset)
        
        # Создаем новую панельку
        builder = InlineKeyboardBuilder()
        
        # Строка 1: Текущий часовой пояс
        builder.add(InlineKeyboardButton(
            text=f"🕐 Текущий: {current_tz}",
            callback_data="timezone_current"
        ))
        builder.adjust(1)
        
        # Строка 2: Популярные часовые пояса
        popular_tz = timezone_db.get_popular_timezones()
        for offset, label in popular_tz:
            if offset != current_offset:  # Не показываем текущий
                builder.add(InlineKeyboardButton(
                    text=label,
                    callback_data=f"timezone_set_{offset}"
                ))
        builder.adjust(4)  # 4 кнопки в ряд
        
        # Строка 3: Точная настройка
        builder.add(InlineKeyboardButton(
            text="⏪ -1 час",
            callback_data="timezone_decrease"
        ))
        builder.add(InlineKeyboardButton(
            text="🔄 Сброс",
            callback_data="timezone_reset"
        ))
        builder.add(InlineKeyboardButton(
            text="⏩ +1 час",
            callback_data="timezone_increase"
        ))
        builder.adjust(3)
        
        text = f"""🕐 **Настройка часового пояса**

Текущий часовой пояс: **{current_tz}**

Выберите часовой пояс для отображения статистики:
• Популярные пояса - быстрый выбор
• Точная настройка - пошаговое изменение
• Изменения применяются автоматически

⚠️ Кулдаун между действиями: 4 секунды"""
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Обновляем владельца панельки (на случай если message_id изменился)
        timezone_panel_owners[callback.message.message_id] = user_id
    except Exception as e:
        logger.error(f"Ошибка при обновлении панельки часовых поясов: {e}")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Проверка наличия токена
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN "
        "или задайте её в config.py. См. env.example для примера."
    )

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Создаем планировщик с экземпляром бота
scheduler = TaskScheduler(bot_instance=bot)

# ====== Глобальный гейт на нажатия кнопок в настройках (только владелец/админ) ======
# Префиксы callback_data, относящиеся к панелям настроек
SETTINGS_CALLBACK_PREFIXES = (
    "settings_",      # корневое меню настроек и навигация
    "warnconfig_",    # настройки варнов
    "rankconfig_",    # настройки рангов/прав
    "russianprefix_", # настройка русского префикса
    "autojoin_",      # автодопуск
)


class SettingsGuardMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if not isinstance(event, CallbackQuery):
                return await handler(event, data)

            cd = (event.data or "")
            # Обрабатываем только кнопки из панелей настроек
            if not cd.startswith(SETTINGS_CALLBACK_PREFIXES):
                return await handler(event, data)

            # Разрешить только владельцу/администратору бота по рангу внутри бота
            chat_id = event.message.chat.id if event.message else None
            user_id = event.from_user.id if event.from_user else None
            if not chat_id or not user_id:
                return await handler(event, data)

            rank = await get_effective_rank(chat_id, user_id)
            if rank not in (RANK_OWNER, RANK_ADMIN):
                await answer_access_denied_callback(event)
                return

            return await handler(event, data)
        except Exception as e:
            logger.error(f"Ошибка в SettingsGuardMiddleware: {e}")
            # На всякий случай не блокируем обработку при ошибке
            return await handler(event, data)


# Регистрируем middleware на callback_query до объявления хэндлеров
dp.callback_query.middleware(SettingsGuardMiddleware())

# Автопринятие заявок на вступление (если включено в настройках чата)
@dp.chat_join_request()
async def handle_chat_join_request(event: ChatJoinRequest):
    try:
        chat_id = event.chat.id
        user_id = event.from_user.id
        
        # Проверяем настройку (с обработкой ошибок, чтобы не блокировать обработку других заявок)
        try:
            enabled = await db.get_auto_accept_join_requests(chat_id)
            if not enabled:
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке авто-принятия для чата {chat_id}: {e}")
            return
        
        # Подтверждаем заявку (основная операция)
        try:
            await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при подтверждении заявки {user_id} в чат {chat_id}: {e}")
            return
        
        # Уведомление владельцу при включенной настройке (неблокирующее - запускаем как фоновую задачу)
        async def send_notification():
            try:
                notify_enabled = await db.get_auto_accept_notify(chat_id)
                if not notify_enabled:
                    return
                
                owner_id = await db.get_chat_owner(chat_id)
                if not owner_id:
                    return
                
                uname = event.from_user.username
                full_name = (event.from_user.first_name or "")
                if event.from_user.last_name:
                    full_name = f"{full_name} {event.from_user.last_name}".strip()
                user_label = f"@{uname}" if uname else (full_name or str(user_id))
                
                chat_info = await db.get_chat(chat_id)
                chat_title = (chat_info or {}).get('chat_title') or str(chat_id)
                await bot.send_message(owner_id, f"✅ Заявка одобрена: {user_label} в чат \"{chat_title}\"")
            except Exception as e:
                # Игнорируем ошибки уведомлений, чтобы не блокировать обработку
                logger.debug(f"Ошибка при отправке уведомления о заявке: {e}")
        
        # Запускаем уведомление в фоне, не ожидая завершения
        asyncio.create_task(send_notification())
        
    except Exception as e:
        logger.error(f"Ошибка при обработке заявки на вступление: {e}")

# Автовыход из зачерненных чатов и блокировка повторного добавления
@dp.my_chat_member()
async def handle_my_chat_member(update: ChatMemberUpdated):
    try:
        if update.new_chat_member and update.new_chat_member.user and update.new_chat_member.user.id == (await bot.get_me()).id:
            chat_id = update.chat.id
            # Если бот добавлен в черный список - покидаем чат
            if await db.is_chat_blacklisted(chat_id):
                try:
                    await bot.leave_chat(chat_id)
                except Exception as leave_err:
                    logger.error(f"Не удалось покинуть зачерненный чат {chat_id}: {leave_err}")
    except Exception as e:
        logger.error(f"Ошибка в handle_my_chat_member: {e}")

# Система кулдаунов для защиты от флуд-контроля
user_cooldowns = {}  # {user_id: last_action_time}
moderation_cooldowns = {}  # {user_id: last_moderation_action_time}
chatnet_update_cooldowns = {}  # {user_id: last_update_time}
hints_config_cooldowns = {}  # {user_id: last_hints_config_change_time}
COOLDOWN_DURATION = 3  # 3 секунды между действиями
MODERATION_COOLDOWN_DURATION = 4  # 4 секунды между действиями модерации
CHATNET_UPDATE_COOLDOWN_DURATION = 600  # 10 минут между обновлениями /chatnet
HINTS_CONFIG_COOLDOWN_DURATION = 60  # 1 минута между изменениями настроек подсказок
shutdown_event = asyncio.Event()


def check_user_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего действия пользователя
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in user_cooldowns:
        last_action = user_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < COOLDOWN_DURATION:
            remaining_time = COOLDOWN_DURATION - time_passed
            return False, int(remaining_time) + 1
    
    # Обновляем время последнего действия
    user_cooldowns[user_id] = current_time
    return True, 0


def check_moderation_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего действия модерации
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in moderation_cooldowns:
        last_action = moderation_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < MODERATION_COOLDOWN_DURATION:
            remaining_time = MODERATION_COOLDOWN_DURATION - time_passed
            return False, int(remaining_time) + 1
    
    # Обновляем время последнего действия модерации
    moderation_cooldowns[user_id] = current_time
    return True, 0


def check_chatnet_update_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего обновления /chatnet
    Возвращает (можно_выполнить, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in chatnet_update_cooldowns:
        last_action = chatnet_update_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < CHATNET_UPDATE_COOLDOWN_DURATION:
            remaining_time = CHATNET_UPDATE_COOLDOWN_DURATION - time_passed
            return False, int(remaining_time)
    
    chatnet_update_cooldowns[user_id] = current_time
    return True, 0

# Инициализация базы данных часовых поясов
timezone_db = TimezoneDatabase(TIMEZONE_DB_PATH)

# Система кулдаунов для панельки часовых поясов
timezone_cooldowns = {}  # {user_id: last_action_time}
TIMEZONE_COOLDOWN_DURATION = 4  # 4 секунды между действиями

# Система отслеживания владельцев панелек часовых поясов
timezone_panel_owners = {}  # {message_id: user_id}


class BotStates(StatesGroup):
    """Состояния бота"""
    waiting_for_action = State()


async def create_main_menu():
    """Создает главное меню - единая функция для всех мест"""
    welcome_text = f"""
🏠 <b>Главное меню</b>

👋 Привет! Я <b>{BOT_NAME}</b> - {BOT_DESCRIPTION}

🌐Мой сайт: https://pixel-ut.pro


Выберите действие:
    """
    
    # Создаем inline клавиатуру
    builder = InlineKeyboardBuilder()
    
    # Кнопка "Добавить в чат" (первая строка, отдельная)
    bot_info = await bot.get_me()
    add_to_chat_url = f"https://t.me/{bot_info.username}?startgroup=true"
    builder.add(InlineKeyboardButton(
        text="➕ Добавить в чат",
        url=add_to_chat_url
    ))

    # Вторая строка: "Друзья" и "Профиль"
    builder.row(
        InlineKeyboardButton(
            text="👥 Друзья",
            callback_data="friends_menu"
        ),
        InlineKeyboardButton(
            text="📊 Мой профиль",
            callback_data="my_profile_private"
        ),
    )

    # Третья строка: "Топ чатов" и "Случайный чат"
    builder.row(
        InlineKeyboardButton(
            text="🏆 Топ чатов",
            callback_data="top_chats"
        ),
        InlineKeyboardButton(
            text="🎲 Случайный чат",
            callback_data="random_chat"
        ),
    )
    
    return welcome_text, builder.as_markup()


async def safe_answer_callback(callback: types.CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback-запрос, игнорирует ошибки устаревших запросов"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        # Игнорируем ошибки (query too old, flood control, etc.) чтобы не прерывать работу бота
        logger.debug(f"Ошибка при ответе на callback: {e}")
        pass


async def fast_edit_message(callback: types.CallbackQuery, text: str, reply_markup=None, parse_mode=None):
    """Быстрое обновление сообщения без задержек для навигации"""
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.debug(f"Ошибка при быстром обновлении сообщения: {e}")
        pass


async def send_access_denied_message(message: Message, chat_id: int, user_id: int):
    """Отправляет сообщение об отказе в доступе пользователю"""
    try:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
    except Exception:
        await message.answer("❌ Недостаточно прав")


async def answer_access_denied_callback(callback: types.CallbackQuery):
    """Отвечает на callback-запрос с сообщением об отказе в доступе"""
    try:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
    except Exception:
        await callback.answer("❌ Недостаточно прав", show_alert=True)


async def update_chat_info_if_needed(chat_id: int) -> bool:
    """Обновление информации о чате при необходимости"""
    try:
        chat_info = await bot.get_chat(chat_id)
        
        # Получаем количество участников
        member_count = None
        try:
            member_count = await bot.get_chat_member_count(chat_id)
            logger.debug(f"Получено количество участников для чата {chat_id}: {member_count}")
        except Exception as e:
            logger.debug(f"Не удалось получить количество участников для чата {chat_id}: {e}")
            # Пробуем альтернативные способы
            try:
                # Для каналов можно попробовать получить информацию через get_chat
                if chat_info.type == 'channel' and hasattr(chat_info, 'member_count'):
                    member_count = chat_info.member_count
                    logger.debug(f"Получено количество участников через get_chat для канала {chat_id}: {member_count}")
                # Для супергрупп тоже можно попробовать
                elif chat_info.type == 'supergroup' and hasattr(chat_info, 'member_count'):
                    member_count = chat_info.member_count
                    logger.debug(f"Получено количество участников через get_chat для супергруппы {chat_id}: {member_count}")
            except Exception as e2:
                logger.debug(f"Альтернативный способ тоже не сработал для чата {chat_id}: {e2}")
        
        # Определяем публичность чата
        is_public = False
        if chat_info.type == 'channel':
            # Каналы всегда публичные
            is_public = True
        elif chat_info.type in ['group', 'supergroup']:
            # Группы публичные если есть username
            is_public = hasattr(chat_info, 'username') and chat_info.username is not None
        
        # Получаем username чата (если есть)
        chat_username = None
        if hasattr(chat_info, 'username') and chat_info.username:
            chat_username = chat_info.username
        
        # Создаем или обновляем invite link для частных чатов
        invite_link = None
        if not is_public and chat_info.type in ['group', 'supergroup']:
            try:
                # Проверяем права администратора
                bot_member = await bot.get_chat_member(chat_id, bot.id)
                if bot_member.status in ['administrator', 'creator']:
                    # Проверяем, есть ли уже сохраненная ссылка
                    chat_db_info = await db.get_chat(chat_id)
                    existing_invite_link = chat_db_info.get('invite_link') if chat_db_info else None
                    
                    # Если ссылки нет или она недействительна, создаем новую
                    if not existing_invite_link:
                        try:
                            # Создаем постоянную invite link (без ограничений)
                            invite_link_obj = await bot.create_chat_invite_link(
                                chat_id=chat_id,
                                name="Bot Auto Link",  # Название ссылки
                                creates_join_request=False,  # Прямое вступление, без заявок
                                expire_date=None,  # Без срока действия
                                member_limit=None  # Без ограничения по количеству
                            )
                            invite_link = invite_link_obj.invite_link
                            logger.info(f"Создана новая invite link для частного чата {chat_id}")
                        except Exception as e:
                            logger.warning(f"Не удалось создать invite link для чата {chat_id}: {e}")
                    else:
                        # Используем существующую ссылку
                        invite_link = existing_invite_link
            except Exception as e:
                logger.debug(f"Не удалось создать/обновить invite link для чата {chat_id}: {e}")
        
        # Если чат стал публичным, удаляем invite link
        if is_public:
            invite_link = None
        
        # Обновляем информацию в базе данных
        logger.debug(f"Обновляем информацию о чате {chat_id}: member_count={member_count}, is_public={is_public}, username={chat_username}, invite_link={'установлена' if invite_link else 'нет'}")
        await db.update_chat_info(
            chat_id=chat_id,
            title=chat_info.title,
            chat_type=chat_info.type,
            member_count=member_count,
            is_active=True,
            is_public=is_public,
            username=chat_username,
            invite_link=invite_link
        )
        
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Обрабатываем ошибки "chat not found" - деактивируем чат и логируем только в DEBUG
        if "chat not found" in error_str or "bad request" in error_str:
            if DEBUG:
                logger.debug(f"Чат {chat_id} не найден при обновлении информации: {e}")
            try:
                await db.deactivate_chat(chat_id)
            except Exception:
                pass
        else:
            logger.error(f"Ошибка при обновлении информации о чате {chat_id}: {e}")
        return False


async def check_admin_rights(bot: Bot, chat_id: int) -> bool:
    """Проверка прав администратора бота в чате"""
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        has_admin = bot_member.status in ['administrator', 'creator']
        
        # Обновляем информацию в базе данных
        await db.update_admin_rights(chat_id, has_admin)
        
        return has_admin
    except Exception as e:
        # Если чат был мигрирован, обновляем ID в базе данных
        if "group chat was upgraded to a supergroup" in str(e):
            # Извлекаем новый ID из ошибки
            import re
            match = re.search(r'with id (-?\d+)', str(e))
            if match:
                new_chat_id = int(match.group(1))
                await db.update_chat_id(chat_id, new_chat_id)
                # Рекурсивно вызываем функцию с новым ID
                return await check_admin_rights(bot, new_chat_id)
        
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


def require_bot_admin_rights(func):
    """Декоратор для проверки прав администратора бота"""
    async def wrapper(message: Message, **kwargs):
        logger.info(f"Команда {func.__name__} вызвана в чате {message.chat.id} ({message.chat.type})")
        
        # Проверяем права администратора бота
        has_bot_admin = await check_admin_rights(bot, message.chat.id)
        logger.info(f"Права администратора бота: {has_bot_admin}")
        
        if not has_bot_admin:
            quote = await get_philosophical_access_denied_message()
            await message.answer(quote)
            return
        
        logger.info("Права администратора бота есть - выполняем команду")
        return await func(message, **kwargs)
    
    return wrapper


def require_admin_rights(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(message: Message, **kwargs):
        logger.info(f"Команда {func.__name__} вызвана в чате {message.chat.id} ({message.chat.type})")
        
        if message.chat.type == 'private':
            logger.info("Личное сообщение - пропускаем проверку прав")
            return await func(message)
        
        has_admin = await check_admin_rights(bot, message.chat.id)
        logger.info(f"Права администратора: {has_admin}")
        
        if not has_admin:
            logger.info("Нет прав администратора - отправляем предупреждение")
            await message.answer(
                "⚠️ **Требуются права администратора!**\n\n"
                "Для работы команд в этом чате мне необходимы права администратора.\n"
                "Пожалуйста, выдайте мне права администратора в настройках группы.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        logger.info("Права администратора есть - выполняем команду")
        return await func(message)
    return wrapper


async def delete_message_after_delay(message: Message, delay: int):
    """Удаляет сообщение после указанной задержки"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения после задержки: {e}")


@dp.message(CommandStart())
async def start_command(message: Message):
    """Обработчик команды /start в личных сообщениях"""
    user = message.from_user
    
    # Проверяем, что это личное сообщение (не группа)
    if message.chat.type != 'private':
        return  # Игнорируем /start в группах
    
    # Сохраняем информацию о пользователе
    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        is_bot=user.is_bot
    )
    
    # Создаем главное меню
    welcome_text, reply_markup = await create_main_menu()
    
    await message.answer(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


@dp.message(F.text.func(lambda text: is_command_alias(text)))
async def command_alias_handler(message: Message):
    """Универсальный обработчик алиасов команд"""
    text = message.text.strip()
    chat_id = message.chat.id
    logger.info(f"command_alias_handler вызван для текста: '{text}' в чате {chat_id} ({message.chat.type})")
    
    # Если это команда /addfriend, пропускаем её
    if text.startswith('/addfriend'):
        logger.info("Пропускаем команду /addfriend в command_alias_handler")
        return
    
    # Проверяем настройку префикса для русских команд
    requires_prefix = await db.get_russian_commands_prefix_setting(chat_id)
    
    if requires_prefix:
        # Если требуется префикс, проверяем что команда начинается с "Пиксель"
        if not text.lower().startswith("пиксель"):
            return  # Игнорируем команду без префикса
        
        # Убираем префикс "Пиксель" и пробелы
        text = text[7:].strip()  # "пиксель" = 7 символов
    
    english_command = get_command_alias(text)
    
    if not english_command:
        return
    
    # Создаем новое сообщение с английской командой
    # Проверяем, есть ли перенос строки (причина на второй строке)
    if '\n' in text:
        # Есть перенос строки - разделяем на команду и причину
        lines = text.split('\n', 1)  # Разделяем только на 2 части
        command_line = lines[0].strip()  # Первая строка - команда
        reason_line = lines[1].strip()   # Вторая строка - причина
        
        # Обрабатываем команду
        words = command_line.split()
        
        # Специальная обработка для myprofile_self - всегда без аргументов
        if english_command == "myprofile_self":
            new_text = f"/{english_command}\n{reason_line}"
        elif english_command == "myprofile" and len(words) >= 2 and words[0] == "кто" and words[1] == "ты":
            # Специальная обработка для "кто ты" - аргументы начинаются с 3-го слова
            if len(words) > 2:
                args = " ".join(words[2:])  # Все слова начиная с 3-го (после "кто ты")
                new_text = f"/{english_command} {args}\n{reason_line}"
            else:
                new_text = f"/{english_command}\n{reason_line}"
        elif len(words) > 1:
            args = " ".join(words[1:])  # Все слова кроме первого (команды)
            new_text = f"/{english_command} {args}\n{reason_line}"  # Добавляем причину с переносом строки
        else:
            new_text = f"/{english_command}\n{reason_line}"
        
        # Создаем новое сообщение без изменения reply_to_message
        new_message = message.model_copy(update={"text": new_text})
    else:
        # Нет переноса строки - обычная обработка
        words = text.split()
        
        # Специальная обработка для myprofile_self - всегда без аргументов
        if english_command == "myprofile_self":
            new_text = f"/{english_command}"
        elif english_command == "myprofile" and len(words) >= 2 and words[0] == "кто" and words[1] == "ты":
            # Специальная обработка для "кто ты" - аргументы начинаются с 3-го слова
            if len(words) > 2:
                args = " ".join(words[2:])  # Все слова начиная с 3-го (после "кто ты")
                new_text = f"/{english_command} {args}"
            else:
                new_text = f"/{english_command}"
        elif len(words) > 1:
            # Команда с аргументами: "мут @user 2 минуты" -> "/mute @user 2 минуты"
            args = " ".join(words[1:])  # Все слова кроме первого (команды)
            new_text = f"/{english_command} {args}"
        else:
            # Команда без аргументов: "стата" -> "/top"
            new_text = f"/{english_command}"
        
        new_message = message.model_copy(update={"text": new_text})
    
    # Отладка
    logger.info(f"Русская команда переведена в английскую в чате {message.chat.id}")

    # Перенаправляем на соответствующий обработчик
    if english_command == "top":
        await top_users_command(new_message)
    elif english_command == "myprofile":
        await myprofile_command(new_message)
    elif english_command == "myprofile_self":
        await myprofile_command(new_message)  
    elif english_command == "settings":
        await settings_command(new_message)
    elif english_command == "ap":
        await ap_command(new_message)
    elif english_command == "unap":
        await unap_command(new_message)
    elif english_command == "selfdemote":
        await selfdemote_command(new_message)
    elif english_command == "staff":
        await staff_command(new_message)
    elif english_command == "mute":
        await mute_command(new_message)
    elif english_command == "unmute":
        await unmute_command(new_message)
    elif english_command == "kick":
        await kick_command(new_message)
    elif english_command == "ban":
        await ban_command(new_message)
    elif english_command == "unban":
        await unban_command(new_message)
    elif english_command == "warn":
        await warn_command(new_message)
    elif english_command == "unwarn":
        await unwarn_command(new_message)
    elif english_command == "topall":
        await top_users_all_chats_command(new_message)
    elif english_command == "raidprotection":
        await raid_protection_command(new_message)
    # Добавляем другие команды по мере необходимости


@dp.callback_query(F.data == "random_chat")
async def random_chat_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'Случайный чат'"""
    user = callback.from_user
    
    # Получаем все активные чаты
    chats = await db.get_all_active_chats()
    
    if not chats:
        await safe_answer_callback(callback, "😔 Пока нет доступных чатов")
        await callback.message.edit_text(
            "😔 К сожалению, пока нет доступных чатов для случайного выбора.\n\n"
            "Добавьте бота в больше чатов, чтобы эта функция заработала!",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
            ).as_markup()
        )
        return
    
    # Выбираем случайный чат, избегая повторения
    import random
    
    # Получаем ID последнего выбранного чата для этого пользователя
    last_chat_key = f"last_random_chat_{user.id}"
    last_chat_id = getattr(random_chat_callback, last_chat_key, None)
    
    # Если есть только один чат, выбираем его
    if len(chats) == 1:
        random_chat = chats[0]
    else:
        # Исключаем последний выбранный чат из списка
        available_chats = [chat for chat in chats if chat['chat_id'] != last_chat_id]
        
        # Если после исключения не осталось чатов, используем все чаты
        if not available_chats:
            available_chats = chats
        
        random_chat = random.choice(available_chats)
    
    # Сохраняем выбранный чат для следующего выбора
    setattr(random_chat_callback, last_chat_key, random_chat['chat_id'])
    
    try:
        # Получаем информацию о чате
        try:
            chat_info = await bot.get_chat(random_chat['chat_id'])
            # Обновляем информацию о чате в базе данных
            await update_chat_info_if_needed(random_chat['chat_id'])
        except Exception as e:
            # Если чат был мигрирован, обновляем ID в базе данных
            if "group chat was upgraded to a supergroup" in str(e):
                # Извлекаем новый ID из ошибки
                import re
                match = re.search(r'with id (-?\d+)', str(e))
                if match:
                    new_chat_id = int(match.group(1))
                    await db.update_chat_id(random_chat['chat_id'], new_chat_id)
                    chat_info = await bot.get_chat(new_chat_id)
                    random_chat['chat_id'] = new_chat_id  # Обновляем ID для дальнейшего использования
                    # Обновляем информацию о чате с новым ID
                    await update_chat_info_if_needed(new_chat_id)
                else:
                    raise e
            else:
                # Если чат недоступен, деактивируем его
                await db.deactivate_chat(random_chat['chat_id'])
                raise e
        
        # Получаем статистику активности
        stats = await db.get_chat_activity_stats(random_chat['chat_id'], 7)
        
        # Формируем сообщение
        chat_text = f"🎲 <b>Случайный чат:</b>\n\n"
        chat_text += f"📝 <b>Название:</b> {chat_info.title}\n"
        
        if chat_info.description:
            chat_text += f"📄 <b>Описание:</b> {chat_info.description[:200]}{'...' if len(chat_info.description) > 200 else ''}\n"
        
        # Показываем статистику активности
        chat_text += f"👥 <b>Активных за неделю:</b> {stats['active_users']}\n"
        chat_text += f"💬 <b>Сообщений за неделю:</b> {stats['total_messages']}\n"
        
        # Создаем клавиатуру
        builder = InlineKeyboardBuilder()
        
        # Все чаты в случайном выборе теперь публичные, поэтому всегда показываем ссылку
        if chat_info.type == 'channel':
            # Публичный канал
            builder.add(InlineKeyboardButton(
                text="📢 Перейти в канал",
                url=f"https://t.me/{chat_info.username}" if chat_info.username else f"https://t.me/c/{str(chat_info.id)[4:]}"
            ))
        elif chat_info.type in ['group', 'supergroup']:
            # Публичная группа/супергруппа
            builder.add(InlineKeyboardButton(
                text="💬 Вступить в чат",
                url=f"https://t.me/{chat_info.username}"
            ))
        
        # Кнопка "Другой чат"
        builder.add(InlineKeyboardButton(
            text="🎲 Другой чат",
            callback_data="random_chat"
        ))
        
        # Кнопка "Назад"
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="back_to_menu"
        ))
        
        # Обновляем сообщение
        try:
            if chat_info.photo:
                # Если у чата есть фото, скачиваем его
                try:
                    # Скачиваем фото чата
                    photo_bytes = await bot.download(chat_info.photo.big_file_id)
                    
                    # Создаем BufferedInputFile из байтов
                    photo_file = BufferedInputFile(photo_bytes.getvalue(), filename="chat_photo.jpg")
                    
                    # Редактируем сообщение с фото
                    await callback.message.edit_media(
                        media=InputMediaPhoto(
                            media=photo_file,
                            caption=chat_text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=builder.as_markup()
                    )
                        
                except Exception as photo_error:
                    if "message is not modified" in str(photo_error):
                        # Сообщение не изменилось, просто отвечаем на callback
                        await safe_answer_callback(callback, "🎲 Информация о чате актуальна")
                    else:
                        logger.error(f"Ошибка при отправке фото чата: {photo_error}")
                        # Если не удалось отправить фото, редактируем как текст
                        try:
                            await callback.message.edit_text(
                                chat_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=builder.as_markup()
                            )
                        except Exception as text_error:
                            if "message is not modified" in str(text_error):
                                await safe_answer_callback(callback, "🎲 Информация о чате актуальна")
                            else:
                                raise text_error
            else:
                # Если фото нет, создаем белый квадрат
                try:
                    # Создаем белый квадрат 512x512
                    from PIL import Image, ImageDraw
                    import io
                    
                    # Создаем белое изображение
                    white_image = Image.new('RGB', (512, 512), 'white')
                    draw = ImageDraw.Draw(white_image)
                    
                    # Добавляем иконку чата в центр
                    draw.ellipse([200, 200, 312, 312], fill='lightgray', outline='gray', width=2)
                    draw.ellipse([220, 220, 292, 292], fill='white')
                    
                    # Конвертируем в байты
                    img_byte_arr = io.BytesIO()
                    white_image.save(img_byte_arr, format='JPEG')
                    img_byte_arr = img_byte_arr.getvalue()
                    
                    # Создаем BufferedInputFile
                    white_photo = BufferedInputFile(img_byte_arr, filename="white_square.jpg")
                    
                    # Редактируем сообщение с белым квадратом
                    await callback.message.edit_media(
                        media=InputMediaPhoto(
                            media=white_photo,
                            caption=chat_text,
                            parse_mode=ParseMode.HTML
                        ),
                        reply_markup=builder.as_markup()
                    )
                    
                except Exception as white_error:
                    if "message is not modified" in str(white_error):
                        # Сообщение не изменилось, просто отвечаем на callback
                        await safe_answer_callback(callback, "🎲 Информация о чате актуальна")
                    else:
                        logger.error(f"Ошибка при создании белого квадрата: {white_error}")
                        # Если не удалось создать белый квадрат, редактируем как текст
                        try:
                            await callback.message.edit_text(
                                chat_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=builder.as_markup()
                            )
                        except Exception as text_error:
                            if "message is not modified" in str(text_error):
                                await safe_answer_callback(callback, "🎲 Информация о чате актуальна")
                            else:
                                raise text_error
        except Exception as e:
            if "message is not modified" in str(e):
                # Сообщение не изменилось, просто отвечаем на callback
                await safe_answer_callback(callback, "🎲 Информация о чате актуальна")
            elif "message to edit not found" in str(e).lower() or "there is no text in the message to edit" in str(e).lower():
                # Сообщение уже удалено или не может быть отредактировано, отправляем новое
                try:
                    if chat_info.photo:
                        # Скачиваем фото чата
                        photo_bytes = await bot.download(chat_info.photo.big_file_id)
                        photo_file = BufferedInputFile(photo_bytes.getvalue(), filename="chat_photo.jpg")
                        await callback.message.answer_photo(
                            photo=photo_file,
                            caption=chat_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=builder.as_markup()
                        )
                    else:
                        # Создаем белый квадрат
                        from PIL import Image, ImageDraw
                        import io
                        
                        white_image = Image.new('RGB', (512, 512), 'white')
                        draw = ImageDraw.Draw(white_image)
                        draw.ellipse([200, 200, 312, 312], fill='lightgray', outline='gray', width=2)
                        draw.ellipse([220, 220, 292, 292], fill='white')
                        
                        img_byte_arr = io.BytesIO()
                        white_image.save(img_byte_arr, format='JPEG')
                        img_byte_arr = img_byte_arr.getvalue()
                        
                        white_photo = BufferedInputFile(img_byte_arr, filename="white_square.jpg")
                        await callback.message.answer_photo(
                            photo=white_photo,
                            caption=chat_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=builder.as_markup()
                        )
                except Exception as send_error:
                    logger.error(f"Ошибка при отправке нового сообщения: {send_error}")
                    # Fallback - отправляем текстовое сообщение
                    try:
                        await callback.message.answer(
                            chat_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=builder.as_markup()
                        )
                    except Exception as fallback_error:
                        logger.error(f"Ошибка при fallback отправке: {fallback_error}")
                        await safe_answer_callback(callback, "❌ Ошибка при обновлении информации о чате")
            else:
                logger.error(f"Неожиданная ошибка при обновлении сообщения: {e}")
                await safe_answer_callback(callback, "❌ Ошибка при обновлении информации о чате")
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о чате {random_chat['chat_id']}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при получении информации о чате")
        try:
            await callback.message.edit_text(
                "❌ Произошла ошибка при получении информации о чате.\n\n"
                "Попробуйте еще раз или выберите другой чат.",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="🎲 Попробовать снова", callback_data="random_chat"),
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
                ).as_markup()
            )
        except Exception as edit_error:
            # Если не удалось отредактировать сообщение (например, оно было удалено), отправляем новое
            logger.error(f"Ошибка при редактировании сообщения: {edit_error}")
            await callback.message.answer(
                "❌ Произошла ошибка при получении информации о чате.\n\n"
                "Попробуйте еще раз или выберите другой чат.",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="🎲 Попробовать снова", callback_data="random_chat"),
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
                ).as_markup()
            )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'Назад' - возврат в главное меню"""
    try:
        # Создаем главное меню
        welcome_text, reply_markup = await create_main_menu()
        
        # Проверяем, есть ли в сообщении фото
        if callback.message.photo:
            # Если есть фото, удаляем сообщение и отправляем новое
            await callback.message.delete()
            await callback.message.answer(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            # Если нет фото, просто редактируем текст
            try:
                await callback.message.edit_text(
                    welcome_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception as edit_error:
                if "message is not modified" in str(edit_error):
                    # Сообщение не изменилось, просто отвечаем на callback
                    await safe_answer_callback(callback, "🏠 Главное меню актуально")
                else:
                    # Если не удалось отредактировать, удаляем и отправляем новое
                    await callback.message.delete()
                    await callback.message.answer(
                        welcome_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в back_to_menu_callback: {e}")
        # Fallback - отправляем новое сообщение
        try:
            welcome_text, reply_markup = await create_main_menu()
            await callback.message.answer(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as fallback_error:
            logger.error(f"Ошибка в fallback back_to_menu_callback: {fallback_error}")
            await callback.answer("❌ Ошибка при возврате в меню")


async def get_top_chats_with_settings(days: int = 3, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Получает топ чатов с учетом настроек показа в топе
    
    Args:
        days: Количество дней для анализа
        limit: Максимальное количество чатов в результате
    
    Returns:
        Список чатов с учетом настроек
    """
    # Получаем больше чатов, чтобы после фильтрации осталось нужное количество
    # Берем в 3 раза больше, чтобы учесть фильтрацию
    all_chats = await db.get_top_chats_by_activity(
        days=days, 
        limit=limit * 3,
        exclude_chat_ids=None,
        include_private=True,  # Получаем и публичные, и частные
        min_activity_threshold=0  # Фильтрацию по порогу сделаем вручную
    )
    
    # Фильтруем чаты по настройкам
    filtered_chats = []
    
    for chat in all_chats:
        settings = get_top_chat_settings(chat['chat_id'])
        show_in_top = settings.get('show_in_top', 'public_only')
        min_threshold = settings.get('min_activity_threshold', 0)
        show_private_label = settings.get('show_private_label', False)
        
        # Проверяем, не исключен ли чат
        if show_in_top == 'never':
            continue
        
        # Проверяем минимальный порог активности
        if chat['total_messages'] < min_threshold:
            continue
        
        # Проверяем видимость
        if show_in_top == 'public_only' and not chat.get('is_public', False):
            continue
        
        # Добавляем информацию о метке "Частный"
        chat['show_private_label'] = show_private_label and not chat.get('is_public', False)
        
        filtered_chats.append(chat)
        
        # Останавливаемся, когда набрали нужное количество
        if len(filtered_chats) >= limit:
            break
    
    return filtered_chats


@dp.callback_query(F.data == "top_chats")
async def top_chats_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'Топ чатов'"""
    try:
        # Получаем топ чатов за последние 3 дня (топ 15) с учетом настроек
        top_chats = await get_top_chats_with_settings(days=3, limit=15)
        
        if not top_chats:
            await safe_answer_callback(callback, "😔 Пока нет активных чатов")
            await callback.message.edit_text(
                "😔 <b>Топ чатов</b>\n\n"
                "К сожалению, пока нет достаточно активных чатов для составления рейтинга.\n\n"
                "Добавьте бота в больше чатов и подождите накопления статистики!",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
                ).as_markup()
            )
            return
        
        # Формируем текст с полным списком
        top_text = "🏆 <b>Топ 15 чатов</b>\n"
        top_text += f"📊 <i>За последние 3 дня</i>\n\n"
        
        # Показываем только краткую статистику
        total_messages = sum(chat['total_messages'] for chat in top_chats)
        top_text += f"📈 <b>Всего сообщений: {total_messages}</b>\n\n"
        
        # Добавляем список чатов в текст
        top_text += "📋 <b>Список чатов:</b>\n"
        for i, chat in enumerate(top_chats, 1):
            # Обрезаем длинные названия для текста
            title = chat['title'][:30] + "..." if len(chat['title']) > 30 else chat['title']
            messages_count = chat['total_messages']
            # Добавляем метку "Частный" если нужно
            private_label = " 🔒" if chat.get('show_private_label', False) else ""
            top_text += f"{i}. {title}{private_label} - {messages_count} сообщений\n"
        
        top_text += "\n💡 <i>Выберите чат для просмотра:</i>"
        
        # Создаем клавиатуру с кнопками для каждого чата (в столбик)
        builder = InlineKeyboardBuilder()
        
        # Добавляем кнопки для всех 15 чатов (в столбик)
        for i, chat in enumerate(top_chats, 1):
            # Обрезаем длинные названия
            title = chat['title'][:25] + "..." if len(chat['title']) > 25 else chat['title']
            # Добавляем метку "Частный" если нужно
            private_label = " 🔒" if chat.get('show_private_label', False) else ""
            builder.add(InlineKeyboardButton(
                text=f"{i}. {title}{private_label}",
                callback_data=f"join_chat_{chat['chat_id']}"
            ))
        
        # Добавляем кнопки управления в одну строку
        builder.row(
            InlineKeyboardButton(text="🔄 Обновить", callback_data="top_chats"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        )
        
        try:
            await callback.message.edit_text(
                top_text,
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
        except Exception as e:
            if "message is not modified" in str(e):
                # Сообщение не изменилось, просто отвечаем на callback
                await safe_answer_callback(callback, "📊 Топ чатов актуален")
            else:
                raise e
        
    except Exception as e:
        logger.error(f"Ошибка при получении топ чатов: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при получении топ чатов")
        await callback.message.edit_text(
            "❌ <b>Ошибка</b>\n\n"
            "Произошла ошибка при получении топ чатов.\n"
            "Попробуйте позже.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
            ).as_markup()
        )


@dp.callback_query(F.data.startswith("join_chat_"))
async def join_chat_callback(callback: types.CallbackQuery):
    """Обработчик кнопки вступления в чат из топа"""
    chat_id = int(callback.data.split("_")[2])
    
    try:
        # Получаем информацию о чате
        try:
            chat_info = await bot.get_chat(chat_id)
        except Exception as e:
            # Если чат был мигрирован, обновляем ID в базе данных
            if "group chat was upgraded to a supergroup" in str(e):
                import re
                match = re.search(r'with id (-?\d+)', str(e))
                if match:
                    new_chat_id = int(match.group(1))
                    await db.update_chat_id(chat_id, new_chat_id)
                    chat_info = await bot.get_chat(new_chat_id)
                    chat_id = new_chat_id
                else:
                    raise e
            else:
                raise e
        
        # Определяем тип чата и показываем соответствующую информацию
        if chat_info.type == 'channel':
            # Публичный канал - показываем ссылку
            channel_text = f"<b>{chat_info.title}</b>\n\n"
            if chat_info.description:
                channel_text += f"{chat_info.description}\n\n"
            
            # Получаем статистику активности за неделю
            try:
                stats = await db.get_chat_activity_stats(chat_id, 7)
                active_users = stats.get('active_users', 0)
                channel_text += f"Активных за неделю: {active_users}\n"
            except Exception:
                channel_text += "Активных за неделю: неизвестно\n"
            
            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()
            if chat_info.username:
                builder.add(InlineKeyboardButton(
                    text="Перейти в канал",
                    url=f"https://t.me/{chat_info.username}"
                ))
            else:
                builder.add(InlineKeyboardButton(
                    text="Перейти в канал",
                    url=f"https://t.me/c/{str(chat_id)[4:]}"
                ))
            builder.add(InlineKeyboardButton(text="Назад к топу", callback_data="top_chats"))
            
            try:
                await callback.message.edit_text(
                    channel_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
            except Exception as e:
                if "message is not modified" in str(e):
                    await safe_answer_callback(callback, "📢 Информация о канале актуальна")
                else:
                    raise e
            
        elif chat_info.type in ['group', 'supergroup']:
            # Все чаты в топе теперь публичные, поэтому всегда показываем ссылку
            group_text = f"<b>{chat_info.title}</b>\n\n"
            if chat_info.description:
                group_text += f"{chat_info.description}\n\n"
            
            # Получаем статистику активности за неделю
            try:
                stats = await db.get_chat_activity_stats(chat_id, 7)
                active_users = stats.get('active_users', 0)
                group_text += f"Активных за неделю: {active_users}\n"
            except Exception:
                group_text += "Активных за неделю: неизвестно\n"
            
            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text="💬 Вступить в чат",
                url=f"https://t.me/{chat_info.username}"
            ))
            builder.add(InlineKeyboardButton(text="Назад к топу", callback_data="top_chats"))
            
            try:
                await callback.message.edit_text(
                    group_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup()
                )
            except Exception as e:
                if "message is not modified" in str(e):
                    await safe_answer_callback(callback, "💬 Информация о чате актуальна")
                else:
                    raise e
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при получении информации о чате")
        await callback.message.edit_text(
            "❌ <b>Ошибка</b>\n\n"
            "Произошла ошибка при получении информации о чате.\n"
            "Попробуйте позже.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="Назад к топу", callback_data="top_chats")
            ).as_markup()
        )


@dp.message(F.left_chat_member)
async def left_chat_member(message: Message):
    """Обработчик удаления бота из чата"""
    # Проверяем, что удалили именно бота
    if message.left_chat_member.id == bot.id:
        chat_id = message.chat.id
        logger.info(f"Бот удален из чата {chat_id}")
        
        # Деактивируем чат в базе данных
        await db.deactivate_chat(chat_id)
        logger.info(f"Чат {chat_id} деактивирован в базе данных")


@dp.message(F.new_chat_members)
async def new_chat_member(message: Message):
    """Обработчик добавления бота в чат и проверка на массовое присоединение"""
    # Проверяем, что бота добавили в группу
    bot_member = None
    for member in message.new_chat_members:
        if member.id == bot.id:
            bot_member = member
            break
    
    # Если бот не добавлен, проверяем на массовое присоединение пользователей
    if not bot_member and message.chat.type in ['group', 'supergroup']:
        # Добавляем всех новых участников в трекинг
        for member in message.new_chat_members:
            await raid_protection_db.add_recent_join(
                chat_id=message.chat.id,
                user_id=member.id,
                username=member.username,
                first_name=member.first_name,
                last_name=member.last_name
            )
        
        # Проверяем на массовое присоединение
        settings = await raid_protection_db.get_settings(message.chat.id)
        is_mass_join, recent_joins = await raid_protection.check_mass_join(message.chat.id, settings)
        
        if is_mass_join:
            # Уведомляем владельца
            chat_title = message.chat.title or "Без названия"
            await raid_protection.notify_owner(
                chat_id=message.chat.id,
                raid_type='mass_join',
                details=f"Обнаружено массовое присоединение в чате {chat_title}",
                recent_joins=recent_joins
            )
        
        return
    
    if not bot_member:
        return
    
    chat = message.chat
    
    # Определяем владельца чата (создателя группы)
    owner_id = None
    if chat.type in ['group', 'supergroup']:
        # Правильно определяем создателя группы через get_chat_administrators
        try:
            admins = await bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == 'creator':
                    owner_id = admin.user.id
                    break
        except Exception as e:
            logger.warning(f"Не удалось определить владельца чата {chat.id}: {e}")
    
    # Сохраняем информацию о чате (только если владелец найден, иначе оставляем None)
    await db.add_chat(
        chat_id=chat.id,
        chat_title=chat.title or "Без названия",
        owner_id=owner_id  # Сохраняем только реального владельца, без fallback
    )
    
    # Проверяем права администратора
    has_admin = await check_admin_rights(bot, chat.id)
    
    # Приветственное сообщение для группы
    if has_admin:
        welcome_text = f"""
🤖 <b>{BOT_NAME}</b> добавлен в чат!

Привет! Я ваш новый помощник для управления чатом.

<b>Доступные команды:</b>
• <code>/help</code> - справка по командам
• <code>/stats</code> - информация о чате  
• <code>/settings</code> - настройки

Готов к работе! 🚀
        """
    else:
        welcome_text = f"""
🤖 <b>{BOT_NAME}</b> добавлен в чат!

⚠️ <b>Внимание!</b> Для полноценной работы бота в этом чате необходимы права администратора.

        """
    
    await send_message_with_gif(message, welcome_text, "welcome", parse_mode=ParseMode.HTML)


@dp.message(F.chat.type == 'private', ~F.text.startswith('/'))
async def private_message_handler(message: Message, state: FSMContext):
    """Обработчик личных сообщений с ботом - обрабатывает только НЕ-команды"""
    # В личных сообщениях бот не учитывает статистику для обычных сообщений
    # Команды обрабатываются отдельными обработчиками
    logger.info(f"Обычное сообщение в ЛС от {message.from_user.id} - игнорируем")
    pass


@dp.message(~F.text.startswith('/'))
async def message_handler(message: Message):
    """Обработчик сообщений: проверка на рейды и подсчет для статистики"""
    # Подсчитываем сообщения только в группах и супергруппах
    if message.chat.type in ['group', 'supergroup']:
        chat_id = message.chat.id
        
        # ПЕРВОЕ: Проверяем сообщение на признаки рейда
        is_raid, raid_type, message_id = await raid_protection.check_message(message)
        
        if is_raid and message_id:
            user_id = message.from_user.id
            
            # Удаляем сообщение (без предупреждения пользователя)
            await raid_protection.delete_message(chat_id, message_id)
            
            # Записываем удаленное сообщение для подсчета
            await raid_protection_db.add_deleted_message(chat_id, user_id, raid_type)
            
            # Проверяем настройки уведомлений и авто-мут
            settings = await raid_protection_db.get_settings(chat_id)
            notification_mode = settings.get('notification_mode', 1)
            auto_mute_duration = settings.get('auto_mute_duration', 0)
            
            # Применяем авто-мут если настроен
            auto_mute_applied = False
            if auto_mute_duration > 0:
                try:
                    # Вычисляем дату окончания мута
                    mute_until = datetime.now() + timedelta(minutes=auto_mute_duration)
                    
                    # Проверяем, есть ли уже активный мут у этого пользователя
                    active_punishments = await moderation_db.get_active_punishments(chat_id, "mute")
                    user_already_muted = any(punish['user_id'] == user_id for punish in active_punishments)
                    
                    if not user_already_muted:
                        # Применяем мут
                        await bot.restrict_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            permissions=types.ChatPermissions(
                                can_send_messages=False,
                                can_send_media_messages=False,
                                can_send_polls=False,
                                can_send_other_messages=False,
                                can_add_web_page_previews=False,
                                can_change_info=False,
                                can_invite_users=False,
                                can_pin_messages=False
                            ),
                            until_date=mute_until
                        )
                        
                        # Записываем наказание в БД
                        await moderation_db.add_punishment(
                            chat_id=chat_id,
                            user_id=user_id,
                            moderator_id=bot.id,
                            punishment_type="mute",
                            reason=f"Автоматический мут за рейд ({raid_type})",
                            expiry_date=mute_until.isoformat(),
                            user_username=message.from_user.username,
                            user_first_name=message.from_user.first_name,
                            moderator_username=None,
                            moderator_first_name=BOT_NAME
                        )
                        
                        auto_mute_applied = True
                        logger.info(f"Автоматический мут применен к пользователю {user_id} в чате {chat_id} на {auto_mute_duration} минут")
                except Exception as e:
                    logger.error(f"Ошибка при применении автоматического мута: {e}")
            
            if auto_mute_applied:
                user_mention = get_user_mention_html(message.from_user)
                duration_text = f"{auto_mute_duration} мин"
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🔇 Участник {user_mention} замучен на {duration_text} за спам!",
                    parse_mode=ParseMode.HTML
                )
            
            # Проверяем только если уведомления включены
            if notification_mode == 1:  # Уведомления включены
                # Проверяем количество уникальных пользователей с удаленными сообщениями за последнюю минуту
                recent_deleted_count = await raid_protection_db.get_recent_deleted_count(chat_id, minutes=1)
                
                # Уведомляем только если >= 3 уникальных пользователей
                if recent_deleted_count >= 3:
                    # Проверяем, прошло ли 60 секунд с последнего уведомления
                    last_notification = await raid_protection_db.get_last_notification_time(chat_id)
                    should_notify = True
                    
                    if last_notification:
                        try:
                            last_notification_time = datetime.fromisoformat(last_notification)
                            time_since_notification = (datetime.now() - last_notification_time).total_seconds()
                            if time_since_notification < 60:
                                should_notify = False  # Не уведомляем, если прошло меньше 60 секунд
                        except ValueError:
                            pass  # Если не удалось распарсить, отправляем уведомление
                    
                    # Уведомляем владельца если нужно
                    if should_notify:
                        chat_title = message.chat.title or "Без названия"
                        
                        await raid_protection.notify_owner(
                            chat_id=chat_id,
                            raid_type=raid_type,
                            user_id=None,  # Показываем общую статистику
                            details=f"Чат: {chat_title}\nУникальных пользователей: {recent_deleted_count}"
                        )
                        
                        # Обновляем время последнего уведомления
                        await raid_protection_db.update_last_notification_time(chat_id, datetime.now().isoformat())
            
            return  # Прерываем обработку, не считаем сообщение
        
        # ВТОРОЕ: Если не рейд, считаем сообщение для статистики
        # Проверяем настройки статистики для чата
        stat_settings = await db.get_chat_stat_settings(chat_id)
        
        # Сообщения всегда записываются в базу для профиля пользователя
        # Но если статистика отключена, не учитываем медиа если настройка выключена
        # Если учет медиа выключен, пропускаем сообщения не-текстовых типов
        if not stat_settings.get('count_media', True):
            # Aiogram выставляет content_type: 'text' для обычных сообщений
            if message.content_type != 'text':
                return
        
        # Получаем информацию о пользователе и чате для логирования
        user_name = message.from_user.first_name or f"@{message.from_user.username}" if message.from_user.username else f"ID{message.from_user.id}"
        chat_name = message.chat.title or "Без названия"
        
        # Проверяем, было ли сообщение от этого пользователя недавно
        last_message_time_str = await db.get_user_last_message_time(chat_id, message.from_user.id)
        current_time = datetime.now()
        
        if last_message_time_str:
            try:
                last_message_time = datetime.fromisoformat(last_message_time_str)
                time_diff = (current_time - last_message_time).total_seconds()
                
                # Если время в базе данных больше текущего (отрицательная разница), это ошибка
                if time_diff < 0:
                    logger.warning(
                        f"⚠️ Некорректное время в БД для пользователя {user_name} ({message.from_user.id}) "
                        f"в чате \"{chat_name}\": время в БД ({last_message_time_str}) больше текущего. "
                        f"Обновляю время в БД."
                    )
                    # Обновляем время в базе данных текущим временем
                    await db.update_user_last_message_time(chat_id, message.from_user.id, current_time.isoformat())
                elif time_diff < 1:  # Меньше 1 секунды (для тестирования)
                    logger.info(f"🚫 Сообщение пропущено от {user_name} ({message.from_user.id}) в чате \"{chat_name}\" (прошло {time_diff:.3f}с)")
                    return
            except ValueError:
                logger.warning(f"Неверный формат времени: {last_message_time_str}")
        
        # Обновляем время последнего сообщения ТОЛЬКО если сообщение будет учтено
        await db.update_user_last_message_time(chat_id, message.from_user.id, current_time.isoformat())
        
        # Проверяем, есть ли запись о чате в базе данных
        chat_info = await db.get_chat(chat_id)
        if not chat_info:
            # Создаем запись о чате если её нет
            owner_id = None
            try:
                # Правильно определяем создателя группы через get_chat_administrators
                admins = await bot.get_chat_administrators(chat_id)
                for admin in admins:
                    if admin.status == 'creator':
                        owner_id = admin.user.id
                        break
            except Exception:
                pass
            
            await db.add_chat(
                chat_id=chat_id,
                chat_title=message.chat.title or "Без названия",
                owner_id=owner_id  # Сохраняем только реального владельца
            )
        
        # Автоматически сохраняем пользователя в базу данных при первом сообщении
        await db.add_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot
        )
        
        # Увеличиваем счетчик сообщений
        await db.increment_message_count(chat_id)
        
        # Увеличиваем счетчик сообщений пользователя
        await db.increment_user_message_count(
            chat_id=chat_id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )

        # Зафиксировать дату первого появления пользователя в этом чате
        await db.ensure_user_first_seen(chat_id, message.from_user.id)
        
        # Информативное логирование
        logger.info(f"✅ Обработано сообщение от {user_name} ({message.from_user.id}) в чате \"{chat_name}\"")


# Примечание: В aiogram 3.x нет встроенного обработчика удаления сообщений
# События удаления сообщений не поддерживаются напрямую через Telegram Bot API
# Для отслеживания удалений потребовался бы более сложный подход с использованием MTProto API
# Пока что оставляем только отслеживание отправки сообщений


# ========== CALLBACK ОБРАБОТЧИКИ ДЛЯ НАСТРОЙКИ ВАРНОВ ==========

async def get_philosophical_access_denied_message():
    """Получить философское сообщение об отказе в доступе"""
    philosophical_quotes = [
        "🌊 Река течет по своему руслу, а не по воле каждого камешка",
        "🍃 Не каждому листу дано управлять направлением ветра", 
        "🌙 Луна светит всем, но не все могут управлять приливами",
        "🌿 Дерево растет вверх, но корни его остаются в земле",
        "🕊️ Птица может летать высоко, но гнездо строит на ветке",
        "🌅 Солнце встает для всех, но не все могут управлять рассветом",
        "🌊 Каждая волна знает свое место в океане",
        "🍂 Осенний лист падает туда, куда его направляет ветер",
        "🌌 Звезды светят всем, но не все могут читать по ним судьбу",
        "🌱 Росток пробивается к свету, но не может управлять солнцем"
    ]
    import random
    return random.choice(philosophical_quotes)

def parse_command_with_reason(text: str) -> tuple[str, str]:
    """
    Парсит команду с причиной на новой строке
    Возвращает (команда_с_аргументами, причина)
    """
    lines = text.strip().split('\n', 1)
    command_line = lines[0]
    reason = lines[1].strip() if len(lines) > 1 else None
    return command_line, reason

def get_reputation_emoji(reputation: int) -> str:
    """Получить эмодзи-индикатор для репутации"""
    if reputation >= 90:
        return "🌟"
    elif reputation >= 70:
        return "✅"
    elif reputation >= 50:
        return "⚠️"
    elif reputation >= 30:
        return "🔴"
    else:
        return "💀"

def get_reputation_progress_bar(reputation: int) -> str:
    """Получить прогресс-бар для репутации"""
    filled = int(reputation / 10)
    empty = 10 - filled
    return "▰" * filled + "▱" * empty

def format_mute_duration(duration_seconds: int) -> str:
    """Форматирование времени мута в читаемый вид"""
    if duration_seconds < 60:  # Меньше минуты
        return f"{duration_seconds}с"
    elif duration_seconds < 3600:  # Меньше часа
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        if seconds > 0:
            return f"{minutes}м {seconds}с"
        else:
            return f"{minutes}м"
    elif duration_seconds < 86400:  # Меньше дня
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}ч {minutes}м"
        else:
            return f"{hours}ч"
    else:  # Дни и больше
        days = duration_seconds // 86400
        hours = (duration_seconds % 86400) // 3600
        if hours > 0:
            return f"{days}д {hours}ч"
        else:
            return f"{days}д"

@dp.callback_query(F.data == "warnconfig_limit")
async def warnconfig_limit_callback(callback: types.CallbackQuery):
    """Обработчик кнопки изменения лимита варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    # Создаем кнопки для выбора лимита (1-10)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    for i in range(1, 11):
        builder.button(text=str(i), callback_data=f"warnlimit_{i}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(5, 5, 1)  # 5 кнопок в ряду, потом 5, потом кнопка назад
    
    await callback.message.edit_text(
        "🔢 <b>Выберите лимит варнов:</b>\n\n"
        "Количество предупреждений, после которых будет применено наказание.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


@dp.callback_query(F.data.startswith("warnlimit_"))
async def warnlimit_set_callback(callback: types.CallbackQuery):
    """Обработчик установки лимита варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    limit = int(callback.data.split("_")[1])
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        # Обновляем настройки
        await moderation_db.update_warn_settings(chat_id, warn_limit=limit)
        
        await safe_answer_callback(callback, f"✅ Лимит варнов установлен: {limit}")
        
        # Возвращаемся к настройкам
        await warnconfig_show_settings(callback.message, chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при установке лимита варнов: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке лимита")


@dp.callback_query(F.data == "warnconfig_punishment")
async def warnconfig_punishment_callback(callback: types.CallbackQuery):
    """Обработчик кнопки изменения типа наказания"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    # Создаем кнопки для выбора наказания
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    builder.button(text="💨 Кик", callback_data="warnpunishment_kick")
    builder.button(text="🔇 Мут", callback_data="warnpunishment_mute")
    builder.button(text="🚫 Бан", callback_data="warnpunishment_ban")
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 1, 1)
    
    await callback.message.edit_text(
        "⚡ <b>Выберите тип наказания:</b>\n\n"
        "• <b>Кик</b> - исключение из чата\n"
        "• <b>Мут</b> - временное ограничение на отправку сообщений\n"
        "• <b>Бан</b> - постоянный запрет на вход в чат",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


@dp.callback_query(F.data.startswith("warnpunishment_"))
async def warnpunishment_set_callback(callback: types.CallbackQuery):
    """Обработчик установки типа наказания"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    punishment_type = callback.data.split("_")[1]
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        # Обновляем настройки
        await moderation_db.update_warn_settings(chat_id, punishment_type=punishment_type)
        
        if punishment_type == 'kick':
            punishment_text = "Кик"
        elif punishment_type == 'mute':
            punishment_text = "Мут"
        elif punishment_type == 'ban':
            punishment_text = "Бан"
        else:
            punishment_text = "Неизвестно"
        await safe_answer_callback(callback, f"✅ Тип наказания установлен: {punishment_text}")
        
        # Возвращаемся к настройкам
        await warnconfig_show_settings(callback.message, chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при установке типа наказания: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке типа наказания")


@dp.callback_query(F.data == "warnconfig_mutetime")
async def warnconfig_mutetime_callback(callback: types.CallbackQuery):
    """Обработчик кнопки изменения времени мута"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    # Создаем кнопки для выбора времени мута
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Предустановленные времена
    times = [
        (300, "5 минут"),
        (900, "15 минут"),
        (1800, "30 минут"),
        (3600, "1 час"),
        (7200, "2 часа"),
        (21600, "6 часов"),
        (43200, "12 часов"),
        (86400, "1 день"),
        (172800, "2 дня"),
        (259200, "3 дня"),
        (432000, "5 дней"),
        (604800, "7 дней"),
        (864000, "10 дней"),
        (1296000, "15 дней"),
        (1728000, "20 дней"),
        (2592000, "30 дней")
    ]
    
    for duration, text in times:
        builder.button(text=text, callback_data=f"warnmutetime_{duration}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 1)  # 2 кнопки в ряду для всех времен + кнопка назад
    
    await callback.message.edit_text(
        "⏰ <b>Выберите время мута:</b>\n\n"
        "Время, на которое пользователь будет замучен при достижении лимита варнов.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


@dp.callback_query(F.data.startswith("warnmutetime_"))
async def warnmutetime_set_callback(callback: types.CallbackQuery):
    """Обработчик установки времени мута"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    duration = int(callback.data.split("_")[1])
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        # Обновляем настройки
        await moderation_db.update_warn_settings(chat_id, mute_duration=duration)
        
        # Форматируем время для отображения
        time_text = format_mute_duration(duration)
        
        await safe_answer_callback(callback, f"✅ Время мута установлено: {time_text}")
        
        # Возвращаемся к настройкам
        await warnconfig_show_settings(callback.message, chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при установке времени мута: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке времени мута")


@dp.callback_query(F.data == "warnconfig_bantime")
async def warnconfig_bantime_callback(callback: types.CallbackQuery):
    """Обработчик кнопки изменения времени бана"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    # Создаем кнопки для выбора времени бана
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Предустановленные времена для бана (более длительные)
    times = [
        (3600, "1 час"),
        (7200, "2 часа"),
        (21600, "6 часов"),
        (43200, "12 часов"),
        (86400, "1 день"),
        (172800, "2 дня"),
        (259200, "3 дня"),
        (432000, "5 дней"),
        (604800, "7 дней"),
        (864000, "10 дней"),
        (1296000, "15 дней"),
        (1728000, "20 дней"),
        (2592000, "30 дней"),
        (5184000, "60 дней"),
        (7776000, "90 дней"),
        (0, "Навсегда")
    ]
    
    for duration, text in times:
        builder.button(text=text, callback_data=f"warnbantime_{duration}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 1)  # 2 кнопки в ряду для всех времен + кнопка назад
    
    await callback.message.edit_text(
        "⏰ <b>Выберите время бана:</b>\n\n"
        "Время, на которое пользователь будет забанен при достижении лимита варнов.\n"
        "После истечения времени пользователь сможет вернуться в чат.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


@dp.callback_query(F.data.startswith("warnbantime_"))
async def warnbantime_set_callback(callback: types.CallbackQuery):
    """Обработчик установки времени бана"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    duration = int(callback.data.split("_")[1])
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        # Обновляем настройки
        await moderation_db.update_warn_settings(chat_id, mute_duration=duration)
        
        # Форматируем время для отображения
        if duration == 0:
            time_text = "Навсегда"
        else:
            time_text = format_mute_duration(duration)
        
        await safe_answer_callback(callback, f"✅ Время бана установлено: {time_text}")
        
        # Возвращаемся к настройкам
        await warnconfig_show_settings(callback.message, chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при установке времени бана: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке времени бана")


@dp.callback_query(F.data == "warnconfig_back")
async def warnconfig_back_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'Назад' в настройках варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    await warnconfig_show_settings(callback.message, chat_id)
    await safe_answer_callback(callback)


# ========== CALLBACK ОБРАБОТЧИКИ ДЛЯ НАСТРОЙКИ РАНГОВ ==========

@dp.callback_query(F.data.startswith("rankconfig_select_"))
async def rankconfig_select_callback(callback: types.CallbackQuery):
    """Обработчик выбора ранга для настройки"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    rank = int(callback.data.split("_")[2])
    await show_rank_permissions(callback.message, chat_id, rank)
    await safe_answer_callback(callback)

@dp.callback_query(F.data == "rankconfig_reset_all")
async def rankconfig_reset_all_callback(callback: types.CallbackQuery):
    """Обработчик сброса всех прав к стандартным"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    try:
        # Сбрасываем права для всех рангов
        for rank in [1, 2, 3, 4, 5]:
            await db.reset_rank_permissions_to_default(chat_id, rank)
        
        await safe_answer_callback(callback, "✅ Все права сброшены к стандартным")
        
        # Возвращаемся к главному меню
        try:
            await show_rankconfig_main_menu(callback.message, chat_id)
        except Exception as e:
            if "message is not modified" in str(e):
                # Сообщение не изменилось, просто отвечаем на callback
                await safe_answer_callback(callback, "✅ Все права сброшены к стандартным")
            else:
                raise e
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе всех прав в чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при сбросе прав")

async def show_rank_permissions(message, chat_id, rank, from_settings: bool | None = None):
    """Показать права конкретного ранга"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        # Получаем права ранга
        permissions = await db.get_all_rank_permissions(chat_id, rank)
        
        # Если прав нет, используем стандартные
        if not permissions:
            permissions = DEFAULT_RANK_PERMISSIONS.get(rank, {})
        
        rank_name = get_rank_name(rank)
        emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
        
        # Формируем сообщение
        message_text = f"{emoji} <b>Права: {rank_name}</b>\n\n"
        
        # Команды модерации
        message_text += "<b>Команды модерации:</b>\n"
        warn_icon = "✅" if permissions.get('can_warn', False) else "❌"
        unwarn_icon = "✅" if permissions.get('can_unwarn', False) else "❌"
        mute_icon = "✅" if permissions.get('can_mute', False) else "❌"
        unmute_icon = "✅" if permissions.get('can_unmute', False) else "❌"
        kick_icon = "✅" if permissions.get('can_kick', False) else "❌"
        ban_icon = "✅" if permissions.get('can_ban', False) else "❌"
        unban_icon = "✅" if permissions.get('can_unban', False) else "❌"
        
        message_text += f"{warn_icon} Варны  {unwarn_icon} Снятие варнов\n"
        message_text += f"{mute_icon} Муты  {unmute_icon} Размуты\n"
        message_text += f"{kick_icon} Кики  {ban_icon} Баны  {unban_icon} Разбаны\n\n"
        
        # Назначение рангов
        message_text += "<b>Назначение рангов:</b>\n"
        assign_4_icon = "✅" if permissions.get('can_assign_rank_4', False) else "❌"
        assign_3_icon = "✅" if permissions.get('can_assign_rank_3', False) else "❌"
        assign_2_icon = "✅" if permissions.get('can_assign_rank_2', False) else "❌"
        remove_icon = "✅" if permissions.get('can_remove_rank', False) else "❌"
        
        message_text += f"{assign_4_icon} Младшие модераторы  {assign_3_icon} Старшие модераторы\n"
        message_text += f"{assign_2_icon} Администраторы  {remove_icon} Снятие рангов\n\n"
        
        # Настройки
        message_text += "<b>Настройки:</b>\n"
        config_warns_icon = "✅" if permissions.get('can_config_warns', False) else "❌"
        config_ranks_icon = "✅" if permissions.get('can_config_ranks', False) else "❌"
        stats_icon = "✅" if permissions.get('can_view_stats', False) else "❌"
        
        message_text += f"{config_warns_icon} Настройки варнов  {config_ranks_icon} Настройки рангов\n"
        message_text += f"{stats_icon} Просмотр статистики"
        
        # Создаем кнопки
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.button(text="⚔️ Команды модерации", callback_data=f"rankconfig_category_{rank}_moderation")
        builder.button(text="👥 Назначение рангов", callback_data=f"rankconfig_category_{rank}_assignment")
        builder.button(text="⚙️ Доступ к настройкам", callback_data=f"rankconfig_category_{rank}_config")
        builder.button(text="📊 Прочее", callback_data=f"rankconfig_category_{rank}_other")
        builder.button(text="🔄 Стандартный конфиг", callback_data=f"rankconfig_reset_{rank}")
        builder.button(text="🔙 Назад", callback_data="rankconfig_back")
        if from_settings:
            builder.button(text="🔙 Назад в настройки", callback_data="settings_main")
        else:
            rank_settings_context.discard((chat_id, message.message_id))

        if from_settings:
            builder.adjust(2, 2, 1, 1, 1)
        else:
            builder.adjust(2, 2, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str or "exactly the same" in error_str:
            # Сообщение не изменилось, это нормально
            logger.debug(f"Сообщение не изменилось при отображении прав ранга {rank} в чате {chat_id}")
        else:
            logger.error(f"Ошибка при отображении прав ранга {rank} в чате {chat_id}: {e}")
            try:
                await message.answer("❌ Ошибка при отображении прав ранга")
            except Exception:
                pass  # Игнорируем ошибки при отправке сообщения об ошибке

async def show_rankconfig_main_menu(message, chat_id, from_settings: bool | None = None):
    """Показать главное меню настроек рангов"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        message_text = (
            "⚙️ <b>Настройка прав рангов</b>\n\n"
            "Выберите ранг для настройки:"
        )
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        for rank in [1, 2, 3, 4]:
            rank_name = get_rank_name(rank)
            emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
            builder.button(text=f"{emoji} {rank_name}", callback_data=f"rankconfig_select_{rank}")
        
        builder.button(text="🔄 Сбросить все к стандарту", callback_data="rankconfig_reset_all")
        if from_settings:
            builder.button(text="🔙 Назад", callback_data="settings_main")
        else:
            rank_settings_context.discard((chat_id, message.message_id))

        if from_settings:
            rank_settings_context.add((chat_id, message.message_id))
            builder.adjust(2, 2, 1, 1)
        else:
            rank_settings_context.discard((chat_id, message.message_id))
            builder.adjust(2, 2, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        if "message is not modified" in str(e):
            # Сообщение не изменилось, это нормально
            logger.debug(f"Сообщение не изменилось в чате {chat_id}")
        else:
            logger.error(f"Ошибка при отображении главного меню настроек рангов в чате {chat_id}: {e}")
            try:
                await message.answer("❌ Ошибка при отображении меню")
            except Exception as e2:
                logger.error(f"Ошибка при отправке сообщения об ошибке: {e2}")

@dp.callback_query(F.data == "rankconfig_back")
async def rankconfig_back_callback(callback: types.CallbackQuery):
    """Обработчик кнопки 'Назад' в настройках рангов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    await show_rankconfig_main_menu(callback.message, chat_id)
    await safe_answer_callback(callback)

@dp.callback_query(F.data.startswith("rankconfig_category_"))
async def rankconfig_category_callback(callback: types.CallbackQuery):
    """Обработчик выбора категории прав"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    # Парсим данные: rankconfig_category_{rank}_{category}
    parts = callback.data.split("_")
    rank = int(parts[2])
    category = parts[3]
    
    await show_rank_category_permissions(callback.message, chat_id, rank, category)
    await safe_answer_callback(callback)

@dp.callback_query(F.data.startswith("rankconfig_reset_"))
async def rankconfig_reset_callback(callback: types.CallbackQuery):
    """Обработчик сброса прав конкретного ранга"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    rank = int(callback.data.split("_")[2])
    
    try:
        # Сбрасываем права для конкретного ранга
        await db.reset_rank_permissions_to_default(chat_id, rank)
        
        rank_name = get_rank_name(rank)
        await safe_answer_callback(callback, f"✅ Права {rank_name} сброшены к стандартным")
        
        # Возвращаемся к просмотру прав ранга
        try:
            await show_rank_permissions(callback.message, chat_id, rank)
        except Exception as e:
            # Ошибки отображения уже обработаны в show_rank_permissions
            # Но если произошла критическая ошибка, логируем её
            error_str = str(e).lower()
            if "message is not modified" not in error_str and "exactly the same" not in error_str:
                logger.error(f"Критическая ошибка при отображении прав ранга {rank} после сброса в чате {chat_id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе прав ранга {rank} в чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при сбросе прав")

async def show_rank_category_permissions(message, chat_id, rank, category, from_settings: bool | None = None):
    """Показать права конкретной категории для ранга"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        # Получаем права ранга
        permissions = await db.get_all_rank_permissions(chat_id, rank)
        
        # Если прав нет, используем стандартные
        if not permissions:
            permissions = DEFAULT_RANK_PERMISSIONS.get(rank, {})
        
        rank_name = get_rank_name(rank)
        emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
        
        # Формируем сообщение в зависимости от категории
        if category == "moderation":
            message_text = f"{emoji} <b>{rank_name} - Команды модерации</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            # Создаем кнопки для команд модерации
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            
            moderation_perms = [
                ('can_warn', 'Варны'),
                ('can_unwarn', 'Снятие варнов'),
                ('can_mute', 'Муты'),
                ('can_unmute', 'Размуты'),
                ('can_kick', 'Кики'),
                ('can_ban', 'Баны'),
                ('can_unban', 'Разбаны')
            ]
            
            for perm_type, perm_name in moderation_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
            builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "assignment":
            message_text = f"{emoji} <b>{rank_name} - Назначение рангов</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            
            assignment_perms = [
                ('can_assign_rank_4', 'Младшие модераторы'),
                ('can_assign_rank_3', 'Старшие модераторы'),
                ('can_assign_rank_2', 'Администраторы'),
                ('can_remove_rank', 'Снятие рангов')
            ]
            
            for perm_type, perm_name in assignment_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
            builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "config":
            message_text = f"{emoji} <b>{rank_name} - Доступ к настройкам</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            
            config_perms = [
                ('can_config_warns', 'Настройки варнов'),
                ('can_config_ranks', 'Настройки рангов')
            ]
            
            for perm_type, perm_name in config_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
            builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "other":
            message_text = f"{emoji} <b>{rank_name} - Прочее</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            
            other_perms = [
                ('can_view_stats', 'Просмотр статистики')
            ]
            
            for perm_type, perm_name in other_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
            builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
        
        # Кнопка "Назад"
        builder.button(text="🔙 Назад", callback_data=f"rankconfig_select_{rank}")
        if from_settings:
            builder.button(text="🔙 Назад в настройки", callback_data="settings_main")
        else:
            rank_settings_context.discard((chat_id, message.message_id))

        if from_settings:
            builder.adjust(2, 2, 1, 1)
        else:
            builder.adjust(2, 2, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении категории {category} для ранга {rank} в чате {chat_id}: {e}")
        await message.answer("❌ Ошибка при отображении категории")

@dp.callback_query(F.data.startswith("rankconfig_toggle_"))
async def rankconfig_toggle_callback(callback: types.CallbackQuery):
    """Обработчик переключения права"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем кулдаун
    can_act, remaining = check_cooldown(user_id)
    if not can_act:
        await safe_answer_callback(callback, f"⏰ Подождите {remaining} секунд перед следующим действием", show_alert=True)
        return
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await safe_answer_callback(callback, quote, show_alert=True)
            return
    
    # Парсим данные: rankconfig_toggle_{rank}_{permission}
    parts = callback.data.split("_")
    rank = int(parts[2])
    permission = "_".join(parts[3:])  # На случай если permission содержит _
    
    try:
        # Получаем текущее значение права
        current_value = await db.get_rank_permission(chat_id, rank, permission)
        
        # Если права нет в БД, используем стандартное
        if current_value is None:
            current_value = DEFAULT_RANK_PERMISSIONS.get(rank, {}).get(permission, False)
        
        # Переключаем значение
        new_value = not current_value
        
        # Сохраняем новое значение
        await db.set_rank_permission(chat_id, rank, permission, new_value)
        
        # Определяем категорию для возврата
        category = "moderation"
        if permission in ['can_assign_rank_4', 'can_assign_rank_3', 'can_assign_rank_2', 'can_remove_rank']:
            category = "assignment"
        elif permission in ['can_config_warns', 'can_config_ranks']:
            category = "config"
        elif permission in ['can_view_stats']:
            category = "other"
        
        # Возвращаемся к категории
        await show_rank_category_permissions(callback.message, chat_id, rank, category)
        
        status = "включено" if new_value else "отключено"
        await safe_answer_callback(callback, f"✅ Право {status}")
        
    except Exception as e:
        logger.error(f"Ошибка при переключении права {permission} для ранга {rank} в чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при изменении права")


async def warnconfig_show_settings(message, chat_id, from_settings: bool | None = None):
    """Функция для отображения настроек варнов"""
    try:
        # Получаем текущие настройки варнов
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        if from_settings is None:
            from_settings = (chat_id, message.message_id) in warn_settings_context
        
        # Формируем сообщение с настройками
        mute_time_text = "Не установлено"
        if warn_settings['mute_duration']:
            mute_time_text = format_mute_duration(warn_settings['mute_duration'])
        
        if warn_settings['punishment_type'] == 'kick':
            punishment_text = "Кик"
        elif warn_settings['punishment_type'] == 'mute':
            punishment_text = "Мут"
        elif warn_settings['punishment_type'] == 'ban':
            punishment_text = "Бан"
        else:
            punishment_text = "Неизвестно"
        
        # Формируем сообщение в зависимости от типа наказания
        if warn_settings['punishment_type'] == 'mute':
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}\n"
                f"⏰ <b>Время мута:</b> {mute_time_text}"
            )
        elif warn_settings['punishment_type'] == 'ban':
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}\n"
                f"⏰ <b>Время бана:</b> {mute_time_text}"
            )
        else:
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}"
            )
        
        # Создаем кнопки
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.button(text="🔢 Изменить лимит", callback_data="warnconfig_limit")
        builder.button(text="⚡ Изменить наказание", callback_data="warnconfig_punishment")
        
        if warn_settings['punishment_type'] == 'mute':
            builder.button(text="⏰ Изменить время мута", callback_data="warnconfig_mutetime")
        elif warn_settings['punishment_type'] == 'ban':
            builder.button(text="⏰ Изменить время бана", callback_data="warnconfig_bantime")
        
        if from_settings:
            builder.button(text="🔙 Назад", callback_data="settings_main")
        else:
            warn_settings_context.discard((chat_id, message.message_id))

        builder.adjust(1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек варнов для чата {chat_id}: {e}")
        await message.edit_text("❌ Ошибка при получении настроек варнов")


@dp.callback_query(F.data.startswith("remove_chat_") & ~F.data.startswith("remove_chat_confirm_"))
async def remove_chat_callback(callback: types.CallbackQuery):
    """Обработчик удаления чата из сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        if len(network_chats) <= 1:
            await callback.answer("❌ Нельзя удалить последний чат из сетки!")
            return
        
        text = f"🗑️ <b>Удаление чата из сетки #{network_id}</b>\n\n"
        text += "Выберите чат для удаления:\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            
            if chat_info:
                # Проверяем доступность чата
                chat_accessible = True
                try:
                    await bot.get_chat(chat_id)
                except Exception:
                    chat_accessible = False
                
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                status_mark = " ❌" if not chat_accessible else ""
                
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}{status_mark}\n"
                
                builder.add(InlineKeyboardButton(
                    text=f"{i}. {chat_info['chat_title']}{primary_mark}{status_mark}",
                    callback_data=f"remove_chat_confirm_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_list"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в remove_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("remove_chat_confirm_"))
async def remove_chat_confirm_callback(callback: types.CallbackQuery):
    """Обработчик подтверждения удаления чата из сетки"""
    try:
        # Парсим данные: remove_chat_confirm_{network_id}_{chat_id}
        parts = callback.data.split("_")
        network_id = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем информацию о чате
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Удаляем чат из сетки
        await network_db.remove_chat_from_network(chat_id)
        
        # Получаем оставшиеся чаты
        remaining_chats = await network_db.get_network_chats(network_id)
        
        if len(remaining_chats) == 0:
            # Если сетка пуста, удаляем её
            await network_db.delete_network(network_id)
            await callback.message.edit_text(
                f"✅ <b>Чат удален из сетки!</b>\n\n"
                f"🗑️ Удален: <b>{chat_title}</b>\n"
                f"🌐 Сетка #{network_id} была удалена (не осталось чатов)\n\n"
                f"Используйте /net для создания новой сетки.",
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.message.edit_text(
                f"✅ <b>Чат удален из сетки!</b>\n\n"
                f"🗑️ Удален: <b>{chat_title}</b>\n"
                f"🌐 Сетка #{network_id} обновлена\n"
                f"📊 Осталось чатов: {len(remaining_chats)}/5\n\n"
                f"Используйте /net для управления сеткой.",
                parse_mode=ParseMode.HTML
            )
        
    except Exception as e:
        logger.error(f"Ошибка в remove_chat_confirm_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.message(Command("help"))
@require_admin_rights
async def help_command(message: Message):
    """Обработчик команды /help"""
    help_text = """
📋 <b>Справка по командам PIXEL</b>

<b>Основные команды:</b>
• <code>/help</code> - эта справка
• <code>/stats</code> - статистика чата
• <code>/top</code> - топ 20 активных пользователей за сегодня
• <code>/topall</code> - топ пользователей за 60 дней в этом чате
• <code>/myprofile</code> - ваш профиль с графиком активности за месяц
• <code>/mytime</code> - настроить часовой пояс для статистики
• <code>/settings</code> - центральное меню настроек
• <code>/autojoin on|off</code> - авто-принятие заявок на вступление
• <code>/statconfig</code> - настройки статистики (админы)
• <code>/refreshchat</code> - обновить информацию о чате
• <code>/cleanup</code> - очистка дубликатов чатов (админы)

<b>Команды модерации:</b>
• <code>/ap @username 3</code> - назначить ранг модератора
• <code>/ap 3</code> - назначить ранг (при ответе на сообщение)
• <code>/unap @username</code> - снять ранг модератора
• <code>/unap</code> - снять ранг (при ответе на сообщение)
• <code>/removmymod</code> - снять свой ранг модератора
• <code>/staff</code> - список модераторов чата
• <code>/mute 10 часов</code> - замутить (при ответе на сообщение)
• <code>/mute @username 10 часов</code> - замутить пользователя
• <code>/unmute</code> - размутить (при ответе на сообщение)
• <code>/unmute @username</code> - размутить пользователя
• <code>/kick @username</code> - исключить из чата
• <code>/kick</code> - исключить (при ответе на сообщение)
• <code>/votemute</code> - создать голосование за мут (при ответе)

<b>Система предупреждений:</b>
• <code>/warn</code> - выдать предупреждение (при ответе)
• <code>/warn @username</code> - выдать предупреждение
• <code>/unwarn</code> - снять предупреждение (при ответе)
• <code>/unwarn @username</code> - снять предупреждение
• <code>/warns</code> - посмотреть предупреждения (при ответе)
• <code>/warns @username</code> - посмотреть предупреждения
• <code>/warnconfig</code> - настройки системы варнов (только админы)

<b>Баны:</b>
• <code>/ban</code> - забанить навсегда (при ответе)
• <code>/ban @username</code> - забанить навсегда
• <code>/ban 1 час</code> - временный бан (при ответе)
• <code>/ban @username 1 час</code> - временный бан
• <code>/unban</code> - разбанить (при ответе)
• <code>/unban @username</code> - разбанить

<b>Настройка прав:</b>
• <code>/rankconfig</code> - настройка прав рангов (владелец)
• <code>/initperms</code> - инициализация прав по умолчанию (владелец)
• <code>/hintsconfig</code> - настройка режима подсказок команд (админы)
• <code>/russianprefix</code> - настройка префикса для русских команд (владелец)

<b>Защита от рейдов:</b>
• <code>/raidprotection</code> - показать настройки защиты от рейдов

<b>Репутация:</b>
• <code>/reputation</code> или <code>/rep</code> - показать свою репутацию
• <code>/reputation @username</code> - показать репутацию пользователя
• <code>/reputation</code> - показать репутацию (при ответе на сообщение)

<b>Упоминания в топах:</b>
• <code>/mentionping</code> - включить кликабельные упоминания (ping) в топах и статистике
• <code>/unmentionping</code> - выключить кликабельные упоминания в топах и статистике

<b>Сетка чатов:</b>
• <code>/net</code> - панель управления сеткой чатов (только ЛС)
• <code>/netconnect &lt;код&gt;</code> - подключить чат к сетке (4-значный код)
• <code>/netadd &lt;код&gt;</code> - добавить чат в существующую сетку (2-значный код)
• <code>/chatnet</code> - информация о сетке чатов
• <code>/chatnet update</code> - обновить информацию о чатах
• <code>/unnet</code> - отключить чат от сетки

<b>Личные сообщения:</b>
• <code>/menu</code> - вернуться в главное меню
• <code>/addfriend &lt;код&gt;</code> - добавить в друзья по коду

<b>Ранги модерации:</b>
• 1 - Владелец 👑
• 2 - Администратор ⚜️
• 3 - Старший модератор 🛡
• 4 - Младший модератор 🔰

<b>🇷🇺 Русские команды:</b>
• <code>стата</code> → <code>/top</code>
• <code>топ</code> → <code>/top</code>
• <code>стата вся</code> → <code>/topall</code>
• <code>статистика вся</code> → <code>/topall</code>
• <code>профиль</code> → <code>/myprofile</code>
• <code>мой профиль</code> → <code>/myprofile</code>
• <code>настройки</code> → <code>/settings</code>
• <code>конфиг</code> → <code>/settings</code>
• <code>автодопуск</code> → <code>/autojoin</code>

<b>🛡️ Модерация:</b>
• <code>мут</code> → <code>/mute</code>
• <code>размут</code> → <code>/unmute</code>
• <code>кик</code> → <code>/kick</code>
• <code>бан</code> → <code>/ban</code>
• <code>разбан</code> → <code>/unban</code>
• <code>варн</code> → <code>/warn</code>
• <code>разварн</code> → <code>/unwarn</code>

💡 <i>Пишите команды без слэша! Можно использовать с аргументами.</i>
    """
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("stats"))
@require_admin_rights
async def stats_command(message: Message):
    """Обработчик команды /stats"""
    chat = message.chat
    
    # Получаем информацию о чате из базы данных
    chat_info = await db.get_chat(chat.id)
    
    # Если информация о чате не найдена, создаем запись
    if not chat_info:
        # Определяем владельца чата
        owner_id = None
        try:
            # Правильно определяем создателя группы через get_chat_administrators
            admins = await bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == 'creator':
                    owner_id = admin.user.id
                    break
        except Exception:
            pass
        
        # Создаем запись о чате
        await db.add_chat(
            chat_id=chat.id,
            chat_title=chat.title or "Без названия",
            owner_id=owner_id  # Сохраняем только реального владельца
        )
        
        # Получаем информацию снова
        chat_info = await db.get_chat(chat.id)
    
    # Получаем количество участников
    try:
        member_count = await bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "Неизвестно"
    
    # Получаем статистику сообщений
    today_count = await db.get_today_message_count(chat.id)
    weekly_stats = await db.get_daily_stats(chat.id, 7)
    
    # Формируем статистику за неделю
    weekly_text = ""
    total_weekly = 0
    if weekly_stats:
        for stat in weekly_stats:
            date_obj = datetime.strptime(stat['date'], '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m')
            weekly_text += f"• {formatted_date}: {stat['message_count']} сообщений\n"
            total_weekly += stat['message_count']
    
    # Получаем информацию о владельце чата
    owner_mention = "Неизвестно"
    try:
        owner_member = await bot.get_chat_member(chat.id, chat_info['owner_id'])
        if owner_member.user.username:
            owner_mention = f"@{owner_member.user.username}"
        elif owner_member.user.first_name:
            owner_mention = f'<a href="tg://user?id={owner_member.user.id}">{owner_member.user.first_name}</a>'
    except Exception:
        pass

    stats_text = f"""
📊 <b>Статистика чата</b>

<b>Основная информация:</b>
• <b>Название:</b> {chat_info['chat_title']}
• <b>ID чата:</b> <code>{chat_info['chat_id']}</code>
• <b>Участников:</b> {member_count}
• <b>Дата добавления бота:</b> {chat_info['added_date'][:10]}
• <b>Владелец:</b> {owner_mention}

<b>📈 Статистика сообщений:</b>
• <b>Сегодня:</b> {today_count} сообщений
• <b>За неделю:</b> {total_weekly} сообщений

<b>📅 Детализация по дням:</b>
{weekly_text if weekly_text else '• Данных пока нет'}

<i>Статистика обновляется в реальном времени</i>
    """
    
    await message.answer(
        stats_text,
        parse_mode=ParseMode.HTML
    )


async def send_private_profile(message: Message, user: types.User):
    """Урезанный профиль для личных сообщений - только рейтинг и глобальная статистика"""
    try:
        # Получаем глобальную активность
        global_activity = await db.get_user_global_activity(user.id)
        
        # Получаем репутацию
        reputation = await reputation_db.get_user_reputation(user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        
        # Формируем имя пользователя
        user_name = get_user_mention_html(user)
        
        # Формируем текст профиля
        profile_lines = [
            f"👤 <b>Профиль: {user_name}</b>",
            "",
            f"🎯 <b>Репутация:</b> {reputation}/100 {reputation_emoji}",
            "",
            "📊 <b>Глобальная статистика:</b>"
        ]
        
        if global_activity and (global_activity.get('today', 0) > 0 or global_activity.get('week', 0) > 0):
            today_count = global_activity.get('today', 0)
            week_count = global_activity.get('week', 0)
            
            profile_lines.extend([
                f"💬 Сегодня: {today_count} сообщений",
                f"📊 За неделю: {week_count} сообщений"
            ])
        else:
            profile_lines.append("📈 Начните общение в чатах для отслеживания статистики")
        
        profile_lines.extend([
            "",
            "💡 <i>Полный профиль с графиком доступен в чатах</i>"
        ])
        
        await message.answer("\n".join(profile_lines), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при создании урезанного профиля: {e}")
        await message.answer("❌ Ошибка при создании профиля")


@dp.message(Command("myprofile"))
@require_admin_rights
async def myprofile_command(message: Message):
    """Профиль пользователя: полный в чатах, урезанный в ЛС"""
    chat_id = message.chat.id
    user = message.from_user
    target_user = user  # По умолчанию - свой профиль
    
    # Проверяем, является ли это ответом на сообщение
    if message.reply_to_message:
        # Если это ответ на сообщение, показываем профиль автора сообщения
        target_user = message.reply_to_message.from_user
    elif message.text and len(message.text.split()) > 1:
        # Парсинг аргументов команды
        args = message.text.split()
        target_user = await parse_user_from_args(message, args, 1)
        
        if not target_user:
            await message.answer("❌ Пользователь не найден в этом чате")
            return
    # Если нет аргументов и нет ответа на сообщение, показываем свой профиль (target_user уже установлен в user)

    # В личных сообщениях показываем урезанный профиль только для себя
    if message.chat.type == 'private':
        await send_private_profile(message, user)
        return

    # В чатах - полный профиль с графиком
    # Проверяем настройку профиля
    stat_settings = await db.get_chat_stat_settings(chat_id)
    if not stat_settings.get('profile_enabled', True):
        await message.answer("📊 Команда профиля отключена для этого чата")
        return
    
    # Обеспечим фиксацию first_seen
    await db.ensure_user_first_seen(chat_id, target_user.id)

    # Данные для профиля
    first_seen = await db.get_user_first_seen(chat_id, target_user.id)
    monthly_stats = await db.get_user_30d_stats(chat_id, target_user.id)
    best_day = await db.get_user_best_day(chat_id, target_user.id)
    global_activity = await db.get_user_global_activity(target_user.id)
    
    # Получаем часовой пояс пользователя
    user_timezone = await timezone_db.get_user_timezone(target_user.id)

    # Сегодняшняя активность в этом чате - используем тот же метод, что и в /top
    today = datetime.now().strftime('%Y-%m-%d')
    today_stats = await db.get_user_daily_stats(chat_id, target_user.id, today)
    today_count = today_stats.get('message_count', 0) if today_stats else 0
    
    # Получаем ранг пользователя
    user_rank = await get_effective_rank(chat_id, target_user.id)
    rank_name = get_rank_name(user_rank)
    
    # Эмодзи для рангов
    rank_emojis = {
        1: "👑",  # Владелец
        2: "⚜️",  # Администратор
        3: "🛡",  # Старший модератор
        4: "🔰",  # Младший модератор
        5: "👤"   # Пользователь
    }
    rank_emoji = rank_emojis.get(user_rank, "👤")

    # Генерируем график
    try:
        chart_buf = generate_modern_profile_card({}, monthly_stats, None)
        
        # Полная подпись с информацией о пользователе
        user_name = get_user_mention_html(target_user)
        
        caption_lines = []
        caption_lines.append(f"👤 Профиль: <b>{user_name}</b> ({rank_emoji} {rank_name})")
        caption_lines.append("")
        
        if first_seen:
            try:
                fs = datetime.strptime(first_seen, '%Y-%m-%d').strftime('%d.%m.%Y')
            except Exception:
                fs = first_seen
            caption_lines.append(f"📅 В чате с: {fs}")
        
        caption_lines.append(f"💬 Сегодня: {today_count} сообщений")
        
        if best_day:
            try:
                bd = datetime.strptime(best_day['date'], '%Y-%m-%d').strftime('%d.%m')
            except Exception:
                bd = best_day['date']
            caption_lines.append(f"🏆 Лучший день: {bd} ({best_day['message_count']})")
        
        # Добавляем информацию о часовом поясе
        tz_label = timezone_db.format_timezone_offset(user_timezone)
        caption_lines.append(f"🕐 Часовой пояс: {tz_label}")
        
        caption_lines.append("")
        caption_lines.append(f"🌍 Глобально: {global_activity['today']} сегодня, {global_activity['week']} за неделю")
        
        # Добавляем информацию о часовом поясе в статистике, если не UTC+3
        if user_timezone != 3:
            caption_lines.append(f"📊 Статистика по {tz_label}")
        
        # Добавляем репутацию
        reputation = await reputation_db.get_user_reputation(target_user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        caption_lines.append(f"🎯 Репутация: {reputation}/100 {reputation_emoji}")

        caption = "\n".join(caption_lines)

        # Отправляем изображение с подписью
        await message.answer_photo(
            types.input_file.BufferedInputFile(chart_buf.read(), filename="profile.png"),
            caption=caption, 
            parse_mode=ParseMode.HTML, 
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации графика профиля: {e}")
        await message.answer("❌ Ошибка при создании графика профиля")


@dp.message(Command("mytime"))
async def mytime_command(message: Message):
    """Настройка часового пояса пользователя"""
    user = message.from_user
    
    # Получаем текущий часовой пояс пользователя
    current_offset = await timezone_db.get_user_timezone(user.id)
    
    # Создаем панельку
    builder = InlineKeyboardBuilder()
    
    # Строка 1: Текущий часовой пояс
    current_tz = timezone_db.format_timezone_offset(current_offset)
    builder.add(InlineKeyboardButton(
        text=f"🕐 Текущий: {current_tz}",
        callback_data="timezone_current"
    ))
    builder.adjust(1)
    
    # Строка 2: Популярные часовые пояса
    popular_tz = timezone_db.get_popular_timezones()
    for offset, label in popular_tz:
        if offset != current_offset:  # Не показываем текущий
            builder.add(InlineKeyboardButton(
                text=label,
                callback_data=f"timezone_set_{offset}"
            ))
    builder.adjust(4)  # 4 кнопки в ряд
    
    # Строка 3: Точная настройка
    builder.add(InlineKeyboardButton(
        text="⏪ -1 час",
        callback_data="timezone_decrease"
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Сброс",
        callback_data="timezone_reset"
    ))
    builder.add(InlineKeyboardButton(
        text="⏩ +1 час",
        callback_data="timezone_increase"
    ))
    builder.adjust(3)
    
    text = f"""🕐 **Настройка часового пояса**

Текущий часовой пояс: **{current_tz}**

Выберите часовой пояс для отображения статистики:
• Популярные пояса - быстрый выбор
• Точная настройка - пошаговое изменение
• Изменения применяются автоматически

⚠️ Кулдаун между действиями: 4 секунды"""
    
    sent_message = await message.answer(
        text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Сохраняем владельца панельки
    timezone_panel_owners[sent_message.message_id] = user.id


@dp.message(Command("addfriend"))
async def addfriend_command(message: Message):
    """Команда для добавления в друзья по коду"""
    logger.info(f"🎯 КОМАНДА /addfriend ВЫЗВАНА! Пользователь {message.from_user.id} в чате {message.chat.id} ({message.chat.type})")
    
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        logger.info("Команда /addfriend вызвана не в личном чате")
        await message.answer("❌ Команда доступна только в личных сообщениях")
        return
    
    user = message.from_user
    args = message.text.split()
    logger.info(f"Аргументы команды: {args}")
    
    if len(args) != 2:
        logger.info("Неверное количество аргументов")
        await message.answer("❌ Неверный формат команды.\nИспользуйте: `/addfriend <код>`\n💡 Код состоит из 6 цифр")
        return
    
    code = args[1].strip()
    logger.info(f"Код для проверки: {code}")
    
    try:
        # Проверяем код
        logger.info("Проверяем код...")
        is_valid, message_text = await friends_db.validate_code(code, user.id)
        logger.info(f"Результат проверки кода: {is_valid}")
        
        if not is_valid:
            await message.answer(message_text)
            return
        
        # Проверяем лимит друзей
        friend_count = await friends_db.get_friend_count(user.id)
        logger.info(f"Количество друзей пользователя: {friend_count}")
        if friend_count >= 5:
            await message.answer("❌ Достигнут лимит друзей (5/5). Удалите кого-то чтобы добавить нового")
            return
        
        # Получаем ID создателя кода
        creator_id = None
        def _get_creator_sync():
            import sqlite3
            with sqlite3.connect(friends_db.db_path) as db:
                cursor = db.execute("SELECT user_id FROM friend_codes WHERE code = ?", (code,))
                row = cursor.fetchone()
                return row[0] if row else None
        
        creator_id = await asyncio.get_event_loop().run_in_executor(None, _get_creator_sync)
        logger.info(f"ID создателя кода: {creator_id}")
        
        if not creator_id:
            logger.info("Код не найден в базе данных")
            await message.answer("❌ Код не найден")
            return
        
        # Добавляем дружбу
        logger.info("Добавляем дружбу...")
        success = await friends_db.add_friendship(creator_id, user.id)
        logger.info(f"Результат добавления дружбы: {success}")
        
        if success:
            # Получаем информацию о создателе кода
            creator_info = await db.get_user(creator_id)
            creator_name = "Неизвестный"
            if creator_info:
                creator_name = creator_info.get('first_name', '')
                if creator_info.get('last_name'):
                    creator_name += f" {creator_info['last_name']}"
                creator_name = creator_name.strip() or f"ID{creator_id}"
            
            # Уведомляем пользователя
            await message.answer(f"✅ Вы успешно добавили в друзья <b>{creator_name}</b>!", parse_mode=ParseMode.HTML)
            
            # Уведомляем создателя кода
            try:
                await bot.send_message(
                    creator_id,
                    f"🎉 <b>Новый друг!</b>\n\n"
                    f"Пользователь <b>{user.first_name or 'ID' + str(user.id)}</b> "
                    f"добавил вас в друзья по вашему коду!",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка при уведомлении создателя кода: {e}")
        else:
            await message.answer("❌ Ошибка при добавлении в друзья")
    
    except Exception as e:
        logger.error(f"Ошибка в addfriend_command: {e}")
        await message.answer("❌ Произошла ошибка при обработке команды")


@dp.message(Command("menu"))
async def menu_command(message: Message):
    """Команда для возврата в главное меню"""
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        await message.answer("❌ Команда доступна только в личных сообщениях")
        return
    
    try:
        # Создаем главное меню
        welcome_text, reply_markup = await create_main_menu()
        
        await message.answer(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    
    except Exception as e:
        logger.error(f"Ошибка в menu_command: {e}")
        await message.answer("❌ Ошибка при загрузке меню")


@dp.message(Command("testfriends"))
async def test_friends_command(message: Message):
    """Тестовая команда для проверки системы друзей"""
    if message.chat.type != 'private':
        await message.answer("❌ Команда доступна только в личных сообщениях")
        return
    
    try:
        user_id = message.from_user.id
        
        # Проверяем количество друзей
        friend_count = await friends_db.get_friend_count(user_id)
        
        # Получаем активные коды пользователя
        user_codes = await friends_db.get_user_active_codes(user_id)
        
        # Получаем все активные коды в системе
        all_codes = await friends_db.get_active_codes()
        
        # Очищаем истекшие коды
        cleaned_count = await friends_db.cleanup_expired_codes()
        
        text = f"🧪 <b>Тест системы друзей</b>\n\n"
        text += f"👤 Ваш ID: <code>{user_id}</code>\n"
        text += f"👥 Количество друзей: {friend_count}/5\n"
        text += f"🔐 Ваших активных кодов: {len(user_codes)}\n"
        text += f"🌐 Всего активных кодов в системе: {len(all_codes)}\n"
        text += f"🧹 Очищено истекших кодов: {cleaned_count}\n"
        
        if user_codes:
            text += "\n📋 <b>Ваши активные коды:</b>\n"
            for code_info in user_codes:
                expires_at = code_info['expires_at'][:19].replace('T', ' ')  # Убираем микросекунды
                text += f"• <code>{code_info['code']}</code> (до {expires_at})\n"
        
        if all_codes:
            text += "\n🌐 <b>Все активные коды в системе:</b>\n"
            for code_info in all_codes[:10]:  # Показываем только первые 10
                expires_at = code_info['expires_at'][:19].replace('T', ' ')
                username_text = f"@{code_info['username']}" if code_info['username'] else ""
                text += f"• <code>{code_info['code']}</code> от {code_info['user_name']} {username_text} (до {expires_at})\n"
            
            if len(all_codes) > 10:
                text += f"... и еще {len(all_codes) - 10} кодов\n"
        
        await message.answer(text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в test_friends_command: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(Command("top"))
@require_admin_rights
async def top_users_command(message: Message):
    """Обработчик команды /top - топ активных пользователей за сегодня"""
    chat = message.chat
    user = message.from_user
    
    # Проверяем настройки статистики
    stat_settings = await db.get_chat_stat_settings(chat.id)
    if not stat_settings['stats_enabled']:
        await message.answer("📊 Статистика отключена для этого чата")
        return
    
    # Получаем часовой пояс пользователя
    user_timezone = await timezone_db.get_user_timezone(user.id)
    
    # Получаем топ пользователей за сегодня с учетом часового пояса
    top_users = await db.get_top_users_today(chat.id, 20, user_timezone)
    
    # Отладочная информация
    logger.info(f"Команда /top в чате {chat.id}: получено {len(top_users) if top_users else 0} пользователей, часовой пояс: {user_timezone}")
    
    if not top_users:
        # Проверяем, есть ли вообще данные в базе для этого чата
        all_stats = await db.get_daily_stats(chat.id, 1)
        logger.info(f"Всего записей статистики для чата {chat.id}: {len(all_stats) if all_stats else 0}")
        
        await message.answer(
            "📊 <b>Топ активных пользователей</b>\n\n"
            "• Данных за сегодня пока нет\n"
            "• Отправьте несколько сообщений для начала статистики",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Формируем сообщение с топом
    today = datetime.now().strftime('%d.%m.%Y')
    
    # Добавляем информацию о часовом поясе, если не UTC+3
    timezone_info = ""
    if user_timezone != 3:
        tz_label = timezone_db.format_timezone_offset(user_timezone)
        timezone_info = f" (статистика по {tz_label})"
    
    # Формируем текстовый список пользователей
    top_text = f"📊 <b>Статистика активности по сообщениям за сутки - {today}{timezone_info}</b>\n\n"
    total_messages = 0
    for i, user in enumerate(top_users, 1):
        user_ping_enabled = await db.get_user_mention_ping_enabled(user['user_id'])
        user_name = get_user_mention_html(user, enable_link=user_ping_enabled)
        top_text += f"{i}. {user_name} - {user['message_count']} сообщений\n"
        total_messages += user['message_count']
    top_text += f"\n💬 <b>Всего сообщений: {total_messages}</b>"
    
    # Генерируем график топ пользователей
    try:
        title = f"Топ активных участников - {today}"
        subtitle = f"За сутки{timezone_info}" if timezone_info else "За сутки"
        chart_buf = await generate_top_chart(top_users, title=title, subtitle=subtitle, bot_instance=bot)
        
        # Читаем буфер один раз
        chart_bytes = chart_buf.read()
        chart_buf.seek(0)  # Возвращаем указатель в начало на случай повторного использования
        
        # Отправляем график с текстовым списком в caption
        try:
            # Формируем параметры для отправки
            photo_params = {
                'photo': types.input_file.BufferedInputFile(chart_bytes, filename="top_users.png"),
                'caption': top_text,
                'parse_mode': ParseMode.HTML,
                'disable_web_page_preview': True
            }
            # Добавляем message_thread_id только если он есть
            if message.chat.type == 'supergroup' and message.message_thread_id:
                photo_params['message_thread_id'] = message.message_thread_id
            
            await message.answer_photo(**photo_params)
        except Exception as photo_error:
            # Обрабатываем ошибку TOPIC_CLOSED или другие ошибки отправки фото
            if "TOPIC_CLOSED" in str(photo_error):
                logger.warning(f"Топик закрыт, отправляем только текст: {photo_error}")
                # Пытаемся отправить только текст
                try:
                    await message.answer(top_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    # Если и текст не отправляется, просто логируем
                    logger.error(f"Не удалось отправить сообщение в закрытый топик: {photo_error}")
            else:
                raise photo_error
    except Exception as e:
        logger.error(f"Ошибка при генерации графика активности для /top: {e}")
        # Fallback на текстовый формат
        try:
            await message.answer(top_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as text_error:
            if "TOPIC_CLOSED" in str(text_error):
                logger.warning(f"Топик закрыт, невозможно отправить сообщение: {text_error}")
            else:
                raise text_error


@dp.message(Command("topall"))
@require_admin_rights
async def top_users_all_chats_command(message: Message):
    """Топ пользователей за последние 60 дней для текущего чата"""
    try:
        chat = message.chat
        # Проверяем настройки статистики
        stat_settings = await db.get_chat_stat_settings(chat.id)
        if not stat_settings['stats_enabled']:
            await message.answer("📊 Статистика отключена для этого чата")
            return

        days = 60
        limit = 30
        top_users = await db.get_top_users_last_days(chat.id, days=days, limit=limit)
        if not top_users:
            await message.answer(
                "📊 <b>Статистика за 60 дней</b>\n\n"
                "• Данных пока нет",
                parse_mode=ParseMode.HTML
            )
            return

        # Обновляем данные пользователей актуальными значениями
        for user in top_users:
            fresh_user_data = await db.get_user(user['user_id'])
            if fresh_user_data:
                user['username'] = fresh_user_data.get('username')
                user['first_name'] = fresh_user_data.get('first_name')
                user['last_name'] = fresh_user_data.get('last_name')
        
        # Формируем текстовый список пользователей
        header = f"📊 <b>Статистика активности за {days} дней — этот чат</b>\n\n"
        lines = []
        total_messages = 0
        for i, user in enumerate(top_users, start=1):
            user_ping_enabled = await db.get_user_mention_ping_enabled(user['user_id'])
            user_name = get_user_mention_html(user, enable_link=user_ping_enabled)
            lines.append(f"{i}. {user_name} — {user['message_count']} сообщений")
            total_messages += user['message_count']
        footer = f"\n💬 <b>Всего сообщений: {total_messages}</b>"
        text_message = header + "\n".join(lines) + footer
        
        # Генерируем график активности по дням
        try:
            # Формируем данные за последние N дней, заполняя пропущенные дни нулями
            # Сначала получаем статистику из базы (может быть меньше дней, если не все дни активны)
            daily_stats = await db.get_daily_stats(chat.id, days)
            
            # Создаем словарь для быстрого доступа
            stats_dict = {}
            if daily_stats:
                stats_dict = {stat['date']: stat['message_count'] for stat in daily_stats}
            
            # Формируем данные за ВСЕ последние N дней, даже если в некоторые дни не было сообщений
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_data = []
            for i in range(days - 1, -1, -1):
                day = today - timedelta(days=i)
                date_str = day.strftime('%Y-%m-%d')
                label = day.strftime('%d.%m')
                count = stats_dict.get(date_str, 0)
                daily_data.append({'label': label, 'count': count})
            
            # Убеждаемся, что у нас действительно 60 дней
            if len(daily_data) != days:
                logger.warning(f"Ожидалось {days} дней, но получили {len(daily_data)} дней для чата {chat.id}")
                # Если что-то пошло не так, создаем заново
                daily_data = []
                for i in range(days - 1, -1, -1):
                    day = today - timedelta(days=i)
                    date_str = day.strftime('%Y-%m-%d')
                    label = day.strftime('%d.%m')
                    count = stats_dict.get(date_str, 0)
                    daily_data.append({'label': label, 'count': count})
            
            # Всегда создаем график, даже если данных мало
            title = f"Активность по дням"
            subtitle = f"За последние {days} дней — этот чат"
            chart_buf = generate_activity_chart(daily_data, title=title, subtitle=subtitle, 
                                               x_label="Дата", is_hourly=False)
            
            # Отправляем график с текстовым списком в caption
            try:
                # Читаем буфер один раз
                chart_bytes = chart_buf.read()
                chart_buf.seek(0)  # Возвращаем указатель в начало на случай повторного использования
                
                # Формируем параметры для отправки
                photo_params = {
                    'photo': types.input_file.BufferedInputFile(chart_bytes, filename="topall_days.png"),
                    'caption': text_message,
                    'parse_mode': ParseMode.HTML,
                    'disable_web_page_preview': True
                }
                # Добавляем message_thread_id только если он есть
                if message.chat.type == 'supergroup' and message.message_thread_id:
                    photo_params['message_thread_id'] = message.message_thread_id
                
                await message.answer_photo(**photo_params)
            except Exception as photo_error:
                # Обрабатываем ошибку TOPIC_CLOSED или другие ошибки отправки фото
                if "TOPIC_CLOSED" in str(photo_error):
                    logger.warning(f"Топик закрыт, отправляем только текст: {photo_error}")
                    # Пытаемся отправить только текст
                    try:
                        # Формируем параметры для отправки текста
                        text_params = {
                            'text': text_message,
                            'parse_mode': ParseMode.HTML,
                            'disable_web_page_preview': True
                        }
                        # Добавляем message_thread_id только если он есть
                        if message.chat.type == 'supergroup' and message.message_thread_id:
                            text_params['message_thread_id'] = message.message_thread_id
                        
                        await message.answer(**text_params)
                    except Exception:
                        # Если и текст не отправляется, просто логируем
                        logger.error(f"Не удалось отправить сообщение в закрытый топик: {photo_error}")
                else:
                    raise photo_error
        except Exception as e:
            logger.error(f"Ошибка при генерации графика активности для /topall: {e}")
            # Fallback на текстовый формат
            try:
                # Формируем параметры для отправки текста
                text_params = {
                    'text': text_message,
                    'parse_mode': ParseMode.HTML,
                    'disable_web_page_preview': True
                }
                # Добавляем message_thread_id только если он есть
                if message.chat.type == 'supergroup' and message.message_thread_id:
                    text_params['message_thread_id'] = message.message_thread_id
                
                await message.answer(**text_params)
            except Exception as text_error:
                if "TOPIC_CLOSED" in str(text_error):
                    logger.warning(f"Топик закрыт, невозможно отправить сообщение: {text_error}")
                else:
                    raise text_error
    except Exception as e:
        logger.error(f"Ошибка в top_users_all_chats_command: {e}")
        # Пытаемся отправить сообщение об ошибке, но если топик закрыт - просто логируем
        try:
            await message.answer("❌ Произошла ошибка при получении статистики")
        except Exception as error_msg:
            if "TOPIC_CLOSED" in str(error_msg):
                logger.warning(f"Топик закрыт, невозможно отправить сообщение об ошибке: {error_msg}")
            else:
                logger.error(f"Не удалось отправить сообщение об ошибке: {error_msg}")


@dp.message(Command("raidprotection"))
@require_admin_rights
async def raid_protection_command(message: Message):
    """Показать настройки защиты от рейдов"""
    chat = message.chat
    settings = await raid_protection_db.get_settings(chat.id)
    
    status_text = "✅ Включена" if settings.get('enabled', True) else "❌ Выключена"
    notification_mode = settings.get('notification_mode', 1)
    
    notif_modes = {0: "🔕 Отключены", 1: "⚠️ Только мощные атаки (≥3)"}
    notif_text = notif_modes.get(notification_mode, "⚠️ Только мощные атаки")
    
    text = (
        f"🛡️ <b>Настройки защиты от рейдов</b>\n\n"
        f"📊 <b>Статус:</b> {status_text}\n"
        f"🔔 <b>Уведомления:</b> {notif_text}\n\n"
        f"<b>Текущие лимиты:</b>\n"
        f"• GIF-спам: {settings.get('gif_limit', 3)} за {settings.get('gif_time_window', 5)}с\n"
        f"• Стикеры: {settings.get('sticker_limit', 5)} за {settings.get('sticker_time_window', 10)}с\n"
        f"• Дубликаты текста: {settings.get('duplicate_text_limit', 3)} за {settings.get('duplicate_text_window', 30)}с\n"
        f"• Массовый вход: {settings.get('mass_join_limit', 10)} за {settings.get('mass_join_window', 60)}с\n\n"
        f"💡 <b>Как изменить:</b>\n"
        f"Используйте /settings для настройки защиты от рейдов."
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("settings"))
@require_admin_rights
@require_bot_admin_rights
async def settings_command(message: Message):
    """Обработчик команды /settings - центральное меню настроек"""
    chat = message.chat
    user = message.from_user
    
    # Проверяем права пользователя
    user_rank = await db.get_user_rank(chat.id, user.id)
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    # Проверяем наличие сетки чатов
    network_info = await network_db.get_network_by_chat(chat.id)
    
    # Текст шапки
    settings_text = (
        "⚙️ <b>Настройки чата</b>\n\n"
        f"👤 <b>Ваш ранг:</b> {RANK_NAMES.get(effective_rank, 'Неизвестно')}\n\n"
        "Выберите раздел настроек ниже:"
    )

    # Инлайн-меню настроек
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    builder.button(text="📊 Статистика", callback_data="settings_open_stat")
    builder.button(text="⚠️ Варны", callback_data="settings_open_warn")
    builder.button(text="🔰 Права/ранги", callback_data="settings_open_ranks")
    builder.button(text="🇷🇺 Префикс команд", callback_data="settings_open_ruprefix")
    builder.button(text="💡 Подсказки", callback_data="settings_open_hints")
    builder.button(text="🚪 Автодопуск", callback_data="settings_open_autojoin")
    builder.button(text="🛡️ Антирейд", callback_data="settings_open_raid")
    builder.button(text="🎬 Гифки", callback_data="settings_open_gifs")
    builder.button(text="🏆 Показ в топе", callback_data="settings_open_top")
    if effective_rank == RANK_OWNER:
        builder.button(text="⚙️ Инициализация прав", callback_data="settings_initperms")
    builder.button(text="🔙 Закрыть", callback_data="settings_close")

    builder.adjust(2, 2, 2, 1, 2, 1, 1)  # разбиение по рядам (Гифки и Показ в топе в одном ряду)

    await message.answer(
        settings_text,
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )


# ====== Само-снятие с модераторского поста ======
@dp.message(Command("removmymod"))
async def selfdemote_command(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)
    # Пользователь должен быть модератором/админом, но не владельцем
    if effective_rank == RANK_OWNER:
        await message.answer("😑 Вы не можете снять себя этой командой.")
        return
    if effective_rank > RANK_JUNIOR_MOD:
        await message.answer("🙂‍↔️ У вас нет модераторского поста.")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"selfdemote_confirm_{user_id}")
    builder.button(text="🔙 Отмена", callback_data=f"selfdemote_cancel_{user_id}")
    builder.adjust(1, 1)

    await message.answer(
        "⚠️ Вы уверены, что хотите снять себя с модераторского поста?",
        reply_markup=builder.as_markup()
    )


 


@dp.callback_query(F.data.startswith("selfdemote_confirm_"))
async def selfdemote_confirm_callback(callback: types.CallbackQuery):
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        # Проверка, что кнопку жмет тот же пользователь
        try:
            suffix = callback.data.split("selfdemote_confirm_", 1)[1]
            initiator_id = int(suffix)
        except Exception:
            initiator_id = None

        if initiator_id != user_id:
            await callback.answer("Эта кнопка не для вас.", show_alert=True)
            return

        effective_rank = await get_effective_rank(chat_id, user_id)
        if effective_rank == RANK_OWNER:
            await callback.answer("Владелец не может снять себя этой кнопкой.", show_alert=True)
            return
        if effective_rank > RANK_JUNIOR_MOD:
            await callback.answer("У вас нет модераторского поста.", show_alert=True)
            return

        success = await db.remove_moderator(chat_id, user_id)
        if success:
            await fast_edit_message(
                callback,
                "✅ Вы сняли себя с модераторского поста. Теперь вы — пользователь.",
                reply_markup=None,
                parse_mode=None,
            )
            await callback.answer("Готово")
        else:
            await callback.answer("Не удалось снять вас с поста. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка selfdemote_confirm_callback: {e}")
        await callback.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("selfdemote_cancel_"))
async def selfdemote_cancel_callback(callback: types.CallbackQuery):
    try:
        user_id = callback.from_user.id
        # Проверка, что кнопку жмет тот же пользователь
        try:
            suffix = callback.data.split("selfdemote_cancel_", 1)[1]
            initiator_id = int(suffix)
        except Exception:
            initiator_id = None

        if initiator_id != user_id:
            await callback.answer("Эта кнопка не для вас.", show_alert=True)
            return

        await fast_edit_message(callback, "❎ Отменено.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка selfdemote_cancel_callback: {e}")
        await callback.answer("Ошибка")

@dp.callback_query(F.data == "settings_open_autojoin")
async def settings_open_autojoin_callback(callback: types.CallbackQuery):
    try:
        chat_id = callback.message.chat.id
        # Проверяем права (только владелец/администратор чата)
        effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
        if effective_rank not in (RANK_OWNER, RANK_ADMIN):
            await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
            return
        enabled = await db.get_auto_accept_join_requests(chat_id)
        notify = await db.get_auto_accept_notify(chat_id)
        status = "Включено ✅" if enabled else "Выключено ❌"
        notify_status = "Вкл." if notify else "Выкл."

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        if enabled:
            builder.button(text="❌ Выключить", callback_data="autojoin_disable")
        else:
            builder.button(text="✅ Включить", callback_data="autojoin_enable")
        if notify:
            builder.button(text="🔕 Откл. уведомления", callback_data="autojoin_notify_disable")
        else:
            builder.button(text="🔔 Вкл. уведомления", callback_data="autojoin_notify_enable")
        builder.button(text="🔙 Назад", callback_data="settings_back_root")
        builder.adjust(1, 1, 1)

        text = (
            "✅ <b>Автодопуск заявок</b>\n\n"
            f"Текущий статус: <b>{status}</b>\n"
            f"Уведомления владельцу: <b>{notify_status}</b>\n\n"
            "Когда включено — бот автоматически одобряет заявки на вступление в чат.\n"
            "Когда выключено — бот игнорирует заявки."
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_autojoin_callback: {e}")
        await callback.answer("Ошибка")

@dp.callback_query(F.data == "settings_open_gifs")
async def settings_open_gifs_callback(callback: types.CallbackQuery):
    """Обработчик открытия настроек гифок"""
    try:
        chat_id = callback.message.chat.id
        # Проверяем права (только владелец/администратор чата)
        effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
        if effective_rank not in (RANK_OWNER, RANK_ADMIN):
            await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
            return
        
        enabled = get_gifs_enabled(chat_id)
        status = "Включено ✅" if enabled else "Выключено ❌"

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        if enabled:
            builder.button(text="❌ Выключить", callback_data="gifs_disable")
        else:
            builder.button(text="✅ Включить", callback_data="gifs_enable")
        builder.button(text="🔙 Назад", callback_data="settings_main")
        builder.adjust(1, 1)

        text = (
            "🎬 <b>Настройки гифок</b>\n\n"
            f"Текущий статус: <b>{status}</b>\n\n"
            "Когда включено — бот отправляет гифки/видео с сообщениями модерации (бан, мут, варн и т.д.).\n"
            "Когда выключено — бот отправляет только текстовые сообщения."
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_gifs_callback: {e}")
        await callback.answer("Ошибка")


@dp.callback_query(F.data == "gifs_enable")
async def gifs_enable_callback(callback: types.CallbackQuery):
    """Включить гифки для чата"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    set_gifs_enabled(chat_id, True)
    await settings_open_gifs_callback(callback)


@dp.callback_query(F.data == "gifs_disable")
async def gifs_disable_callback(callback: types.CallbackQuery):
    """Выключить гифки для чата"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    set_gifs_enabled(chat_id, False)
    await settings_open_gifs_callback(callback)


@dp.callback_query(F.data == "autojoin_enable")
async def autojoin_enable_callback(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_join_requests(chat_id, True)
    await settings_open_autojoin_callback(callback)

@dp.callback_query(F.data == "autojoin_disable")
async def autojoin_disable_callback(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_join_requests(chat_id, False)
    await settings_open_autojoin_callback(callback)

@dp.callback_query(F.data == "autojoin_notify_enable")
async def autojoin_notify_enable_callback(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_notify(chat_id, True)
    await settings_open_autojoin_callback(callback)

@dp.callback_query(F.data == "autojoin_notify_disable")
async def autojoin_notify_disable_callback(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await db.set_auto_accept_notify(chat_id, False)
    await settings_open_autojoin_callback(callback)

@dp.callback_query(F.data == "settings_back_root")
async def settings_back_root_callback(callback: types.CallbackQuery):
    # Вернуться к корню настроек
    try:
        chat = callback.message.chat
        user = callback.from_user
        effective_rank = await get_effective_rank(chat.id, user.id)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="📊 Статистика", callback_data="settings_open_stat")
        builder.button(text="⚠️ Варны", callback_data="settings_open_warn")
        builder.button(text="🔰 Права/ранги", callback_data="settings_open_ranks")
        builder.button(text="🇷🇺 Префикс команд", callback_data="settings_open_ruprefix")
        builder.button(text="💡 Подсказки", callback_data="settings_open_hints")
        builder.button(text="🚪 Автодопуск", callback_data="settings_open_autojoin")
        builder.button(text="🛡️ Антирейд", callback_data="settings_open_raid")
        if effective_rank == RANK_OWNER:
            builder.button(text="⚙️ Инициализация прав", callback_data="settings_initperms")
        builder.button(text="🔙 Закрыть", callback_data="settings_close")
        builder.adjust(2, 2, 2, 1, 1)
        settings_text = (
            "⚙️ <b>Настройки чата</b>\n\n"
            f"👤 <b>Ваш ранг:</b> {RANK_NAMES.get(effective_rank, 'Неизвестно')}\n\n"
            "Выберите раздел настроек ниже:"
        )
        await callback.message.edit_text(settings_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_back_root_callback: {e}")
        await callback.answer("Ошибка")


@dp.message(Command("autojoin"))
@require_admin_rights
@require_bot_admin_rights
async def autojoin_command(message: Message):
    """Включить/выключить авто-принятие заявок: /autojoin on|off"""
    chat = message.chat
    args = (message.text or "").split()
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        current = await db.get_auto_accept_join_requests(chat.id)
        status = "включено" if current else "выключено"
        await message.answer(
            "⚙️ <b>Авто-принятие заявок</b>\n\n"
            f"Текущее состояние: <b>{status}</b>\n"
            "Используйте: <code>/autojoin on</code> или <code>/autojoin off</code>",
            parse_mode=ParseMode.HTML
        )
        return
    enabled = args[1].lower() == "on"
    await db.set_auto_accept_join_requests(chat.id, enabled)
    await message.answer("✅ Авто-принятие заявок " + ("включено" if enabled else "выключено"))


@dp.message(Command("russianprefix"))
@require_admin_rights
@require_bot_admin_rights
async def russianprefix_command(message: Message):
    """Команда настройки префикса для русских команд"""
    chat = message.chat
    user = message.from_user
    
    # Проверяем права пользователя (только владелец)
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await message.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    # Получаем текущую настройку
    current_setting = await db.get_russian_commands_prefix_setting(chat.id)
    
    # Создаем inline клавиатуру
    builder = InlineKeyboardBuilder()
    
    if current_setting:
        # Сейчас включен префикс, предлагаем отключить
        builder.add(InlineKeyboardButton(
            text="❌ Отключить префикс",
            callback_data="russianprefix_disable"
        ))
        status_text = "✅ <b>Включен</b> - русские команды требуют префикс \"Пиксель\""
        example_text = "Пример: <code>Пиксель стата</code> или <code>Пиксель мут @user 5 минут</code>"
    else:
        # Сейчас отключен префикс, предлагаем включить
        builder.add(InlineKeyboardButton(
            text="✅ Включить префикс",
            callback_data="russianprefix_enable"
        ))
        status_text = "❌ <b>Отключен</b> - русские команды работают без префикса"
        example_text = "Пример: <code>стата</code> или <code>мут @user 5 минут</code>"
    
    builder.adjust(1)
    
    settings_text = f"""
🇷🇺 <b>Настройка префикса для русских команд</b>

📊 <b>Текущий статус:</b> {status_text}

📝 <b>Описание:</b>
Эта настройка помогает избежать конфликтов с другими ботами. 
Когда включена, русские команды должны начинаться с "Пиксель".

{example_text}

💡 <b>Рекомендация:</b> Включите префикс в чатах с несколькими ботами.
    """
    
    await message.answer(
        settings_text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(F.data == "russianprefix_enable")
async def russianprefix_enable_callback(callback: types.CallbackQuery):
    """Включить префикс для русских команд"""
    chat = callback.message.chat
    user = callback.from_user
    
    # Проверяем права пользователя (только владелец)
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    # Включаем префикс
    success = await db.set_russian_commands_prefix_setting(chat.id, True)
    
    if success:
        await callback.message.edit_text(
            "✅ <b>Префикс для русских команд включен!</b>\n\n"
            "Теперь русские команды должны начинаться с \"Пиксель\":\n"
            "• <code>Пиксель стата</code>\n"
            "• <code>Пиксель мут @user 5 минут</code>\n"
            "• <code>Пиксель настройки</code>\n\n"
            "Это поможет избежать конфликтов с другими ботами.",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Ошибка при изменении настройки!")
    
    await callback.answer()


@dp.callback_query(F.data == "russianprefix_disable")
async def russianprefix_disable_callback(callback: types.CallbackQuery):
    """Отключить префикс для русских команд"""
    chat = callback.message.chat
    user = callback.from_user
    
    # Проверяем права пользователя (только владелец)
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    # Отключаем префикс
    success = await db.set_russian_commands_prefix_setting(chat.id, False)
    
    if success:
        await callback.message.edit_text(
            "❌ <b>Префикс для русских команд отключен!</b>\n\n"
            "Теперь русские команды работают без префикса:\n"
            "• <code>стата</code>\n"
            "• <code>мут @user 5 минут</code>\n"
            "• <code>настройки</code>\n\n"
            "⚠️ <b>Внимание:</b> Это может вызвать конфликты с другими ботами.",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Ошибка при изменении настройки!")
    
    await callback.answer()


@dp.callback_query(F.data == "settings_close")
async def settings_close_callback(callback: types.CallbackQuery):
    """Закрыть меню настроек"""
    if not await _ensure_admin(callback):
        await answer_access_denied_callback(callback)
        return
    warn_settings_context.discard((callback.message.chat.id, callback.message.message_id))
    rank_settings_context.discard((callback.message.chat.id, callback.message.message_id))
    try:
        await callback.message.delete()
    except Exception:
        await callback.answer("Закрыто")


async def _ensure_admin(callback: types.CallbackQuery) -> bool:
    """Проверка, что действия с меню выполняет владелец/администратор."""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    try:
        effective_rank = await get_effective_rank(chat_id, user_id)
        if effective_rank <= 2:
            return True
        await answer_access_denied_callback(callback)
        return False
    except Exception:
        await answer_access_denied_callback(callback)
        return False


warn_settings_context: set[tuple[int, int]] = set()
rank_settings_context: set[tuple[int, int]] = set()


def _is_rank_settings_context(chat_id: int, message_id: int) -> bool:
    return (chat_id, message_id) in rank_settings_context


@dp.callback_query(F.data == "settings_open_warn")
async def settings_open_warn_callback(callback: types.CallbackQuery):
    """Открыть настройки системы предупреждений из главного меню"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
        return

    try:
        warn_settings_context.add((chat_id, callback.message.message_id))
        await warnconfig_show_settings(callback.message, chat_id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_warn_callback в чате {chat_id}: {e}")
        await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "settings_open_ranks")
async def settings_open_ranks_callback(callback: types.CallbackQuery):
    """Открыть настройки прав рангов прямо в меню"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
        return

    try:
        rank_settings_context.add((chat_id, callback.message.message_id))
        await show_rankconfig_main_menu(callback.message, chat_id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_ranks_callback в чате {chat_id}: {e}")
        await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "settings_open_hints")
async def settings_open_hints_callback(callback: types.CallbackQuery):
    """Открыть панель настройки подсказок без отдельной команды"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    try:
        text, markup = await build_hints_settings_panel(chat_id)
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_hints_callback в чате {chat_id}: {e}")
        await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "settings_initperms")
async def settings_initperms_callback(callback: types.CallbackQuery):
    """Показать предупреждение и подтверждение сброса прав рангов"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)

    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец может инициализировать права", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="initperms_confirm")
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1, 1)

    text = (
        "⚙️ <b>Инициализация прав рангов</b>\n\n"
        "Действие сбросит права всех рангов к стандартным настройкам по умолчанию.\n"
        "Продолжить?"
    )

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "initperms_confirm")
async def initperms_confirm_callback(callback: types.CallbackQuery):
    """Подтверждение инициализации прав рангов"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)

    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец может выполнять действие", show_alert=True)
        return

    try:
        success = await db.initialize_rank_permissions(chat_id)
        if success:
            message_text = (
                "✅ <b>Права рангов сброшены</b>\n\n"
                "Все значения возвращены к стандартной конфигурации."
            )
            await callback.answer("Готово")
        else:
            message_text = "❌ Не удалось инициализировать права. Попробуйте позже."
            await callback.answer("❌ Ошибка", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка initperms_confirm_callback в чате {chat_id}: {e}")
        message_text = "❌ Произошла ошибка при инициализации прав"
        await callback.answer("❌ Ошибка", show_alert=True)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1)

    await callback.message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())


@dp.callback_query(F.data == "settings_open_stat")
async def settings_open_stat_callback(callback: types.CallbackQuery):
    """Открыть настройки статистики в том же сообщении"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()

        stats_icon = "✅" if stat_settings['stats_enabled'] else "❌"
        builder.button(text=f"{stats_icon} Статистика включена", callback_data="statconfig_toggle_stats")
        # Медиа toggle
        media_icon = "✅" if stat_settings.get('count_media', True) else "❌"
        builder.button(text=f"{media_icon} Считать медиа", callback_data="statconfig_toggle_media")
        # Профиль toggle
        profile_icon = "✅" if stat_settings.get('profile_enabled', True) else "❌"
        builder.button(text=f"{profile_icon} Команда профиля", callback_data="statconfig_toggle_profile")
        builder.adjust(1)
        builder.button(text="🔙 Назад", callback_data="settings_main")

        message_text = "📊 <b>Настройки статистики</b>\n\n"
        message_text += f"📈 Статистика: {'включена' if stat_settings['stats_enabled'] else 'отключена'}\n"
        message_text += "⏱️ Временной интервал: 1 секунда (все сообщения)\n\n"
        message_text += "Выберите настройку для изменения:"

        await callback.message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
        )
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        await callback.answer()
    except Exception:
        await callback.answer("❌ Ошибка при открытии настроек", show_alert=True)


@dp.callback_query(F.data == "settings_open_ruprefix")
async def settings_open_ruprefix_callback(callback: types.CallbackQuery):
    """Открыть настройку префикса русских команд"""
    if not await _ensure_admin(callback):
        return

    chat = callback.message.chat
    user_id = callback.from_user.id

    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец чата может изменить эту настройку!", show_alert=True)
        return

    current_setting = await db.get_russian_commands_prefix_setting(chat.id)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if current_setting:
        builder.button(text="❌ Отключить префикс", callback_data="russianprefix_disable")
        status_text = "✅ <b>Включен</b> - русские команды требуют префикс \"Пиксель\""
        example_text = "Пример: <code>Пиксель стата</code> или <code>Пиксель мут @user 5 минут</code>"
    else:
        builder.button(text="✅ Включить префикс", callback_data="russianprefix_enable")
        status_text = "❌ <b>Отключен</b> - русские команды работают без префикса"
        example_text = "Пример: <code>стата</code> или <code>мут @user 5 минут</code>"

    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="settings_main")

    settings_text = (
        "🇷🇺 <b>Настройка префикса для русских команд</b>\n\n"
        f"📊 <b>Текущий статус:</b> {status_text}\n\n"
        "📝 <b>Описание:</b>\n"
        "Эта настройка помогает избежать конфликтов с другими ботами. \n"
        "Когда включена, русские команды должны начинаться с \"Пиксель\".\n\n"
        f"{example_text}\n\n"
        "💡 <b>Рекомендация:</b> Включите префикс в чатах с несколькими ботами."
    )

    await callback.message.edit_text(settings_text, parse_mode=ParseMode.HTML)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "settings_open_raid")
async def settings_open_raid_callback(callback: types.CallbackQuery):
    """Открыть настройки защиты от рейдов"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat.id)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Кнопка включения/выключения
    if settings.get('enabled', True):
        builder.button(text="❌ Выключить защиту", callback_data="raid_toggle")
        status_text = "✅ <b>Включена</b>"
    else:
        builder.button(text="✅ Включить защиту", callback_data="raid_toggle")
        status_text = "❌ <b>Выключена</b>"
    
    builder.adjust(1)
    
    # Кнопки настройки уведомлений
    notification_mode = settings.get('notification_mode', 1)
    if notification_mode == 0:
        notif_text = "Отключены"
        builder.button(text="✅ Включить уведомления", callback_data="raid_notif_1")
    else:  # mode == 1
        notif_text = "Только мощные атаки (≥3 пользователей)"
        builder.button(text="❌ Выключить уведомления", callback_data="raid_notif_0")
    
    # Кнопка настройки авто-мута
    auto_mute = settings.get('auto_mute_duration', 0)
    if auto_mute == 0:
        builder.button(text="🔇 Авто-мут: Выкл", callback_data="raid_mute_settings")
        mute_text = "Выключен"
    else:
        builder.button(text=f"🔇 Авто-мут: {auto_mute} мин", callback_data="raid_mute_settings")
        mute_text = f"{auto_mute} минут"
    
    # Определяем текущий пресет по настройкам
    current_preset = None
    current_gif = settings.get('gif_limit', 3)
    current_gif_window = settings.get('gif_time_window', 5)
    current_sticker = settings.get('sticker_limit', 5)
    current_sticker_window = settings.get('sticker_time_window', 10)
    current_text = settings.get('duplicate_text_limit', 3)
    current_text_window = settings.get('duplicate_text_window', 30)
    current_join = settings.get('mass_join_limit', 10)
    current_join_window = settings.get('mass_join_window', 60)
    
    presets = {
        'light': {
            'gif_limit': 10, 'gif_window': 15,
            'sticker_limit': 10, 'sticker_window': 20,
            'text_limit': 5, 'text_window': 60,
            'join_limit': 20, 'join_window': 120
        },
        'medium': {
            'gif_limit': 5, 'gif_window': 10,
            'sticker_limit': 7, 'sticker_window': 15,
            'text_limit': 3, 'text_window': 40,
            'join_limit': 15, 'join_window': 90
        },
        'strict': {
            'gif_limit': 2, 'gif_window': 5,
            'sticker_limit': 3, 'sticker_window': 10,
            'text_limit': 2, 'text_window': 20,
            'join_limit': 7, 'join_window': 60
        }
    }
    
    for preset_name, preset_values in presets.items():
        if (current_gif == preset_values['gif_limit'] and current_gif_window == preset_values['gif_window'] and
            current_sticker == preset_values['sticker_limit'] and current_sticker_window == preset_values['sticker_window'] and
            current_text == preset_values['text_limit'] and current_text_window == preset_values['text_window'] and
            current_join == preset_values['join_limit'] and current_join_window == preset_values['join_window']):
            current_preset = preset_name
            break
    
    # Добавляем кнопки для настройки уровней защиты
    if current_preset == 'light':
        builder.button(text="✅ Слабая", callback_data="raid_preset_light")
    else:
        builder.button(text="🟢 Слабая", callback_data="raid_preset_light")
    
    if current_preset == 'medium':
        builder.button(text="✅ Средняя", callback_data="raid_preset_medium")
    else:
        builder.button(text="🟡 Средняя", callback_data="raid_preset_medium")
    
    if current_preset == 'strict':
        builder.button(text="✅ Строгая", callback_data="raid_preset_strict")
    else:
        builder.button(text="🔴 Строгая", callback_data="raid_preset_strict")
    
    builder.button(text="🔙 Назад", callback_data="settings_main")
    
    preset_names = {'light': 'Слабая', 'medium': 'Средняя', 'strict': 'Строгая'}
    current_preset_text = preset_names[current_preset] if current_preset else "Пользовательская"
    
    settings_text = (
        "🛡️ <b>Настройки защиты от рейдов</b>\n\n"
        f"📊 <b>Защита:</b> {status_text}\n"
        f"🔔 <b>Уведомления владельцу:</b> {notif_text}\n"
        f"🔇 <b>Авто-мут:</b> {mute_text}\n\n"
        f"<b>Текущий пресет:</b> {current_preset_text}\n\n"
        "<b>Текущие лимиты:</b>\n"
        f"• GIF-спам: {settings.get('gif_limit', 3)} за {settings.get('gif_time_window', 5)}с\n"
        f"• Стикеры: {settings.get('sticker_limit', 5)} за {settings.get('sticker_time_window', 10)}с\n"
        f"• Текст: {settings.get('duplicate_text_limit', 3)} за {settings.get('duplicate_text_window', 30)}с\n"
        f"• Массовый вход: {settings.get('mass_join_limit', 10)} за {settings.get('mass_join_window', 60)}с\n\n"
        "💡 <b>Быстрая настройка:</b>\n"
        "Выберите уровень защиты."
    )
    
    builder.adjust(1, 1, 1, 3, 1)
    
    await callback.message.edit_text(settings_text, parse_mode=ParseMode.HTML)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "raid_toggle")
async def raid_toggle_callback(callback: types.CallbackQuery):
    """Переключить защиту от рейдов"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat.id)
    new_status = not settings.get('enabled', True)
    
    await raid_protection_db.update_setting(chat.id, 'enabled', new_status)
    
    # Перенаправляем обратно в меню настроек рейдов
    await settings_open_raid_callback(callback)
    await callback.answer(f"✅ Защита {'включена' if new_status else 'выключена'}")


@dp.callback_query(F.data.startswith("raid_notif_"))
async def raid_notification_mode_callback(callback: types.CallbackQuery):
    """Изменить режим уведомлений защиты от рейдов"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    # Получаем режим уведомлений из callback_data
    mode_str = callback.data.split("_")[2]
    new_mode = int(mode_str)
    
    await raid_protection_db.update_setting(chat.id, 'notification_mode', new_mode)
    
    mode_names = {0: "Отключены", 1: "Включены"}
    
    # Перенаправляем обратно в меню настроек рейдов
    await settings_open_raid_callback(callback)
    await callback.answer(f"✅ Уведомления: {mode_names[new_mode]}")


@dp.callback_query(F.data.startswith("raid_preset_"))
async def raid_preset_callback(callback: types.CallbackQuery):
    """Применить предустановленный уровень защиты от рейдов"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    preset_type = callback.data.split("_")[2]
    
    # Определяем настройки для каждого уровня
    presets = {
        'light': {
            'name': 'Слабая защита',
            'gif_limit': 10,
            'gif_time_window': 15,
            'sticker_limit': 10,
            'sticker_time_window': 20,
            'duplicate_text_limit': 5,
            'duplicate_text_window': 60,
            'mass_join_limit': 20,
            'mass_join_window': 120
        },
        'medium': {
            'name': 'Средняя защита',
            'gif_limit': 5,
            'gif_time_window': 10,
            'sticker_limit': 7,
            'sticker_time_window': 15,
            'duplicate_text_limit': 3,
            'duplicate_text_window': 40,
            'mass_join_limit': 15,
            'mass_join_window': 90
        },
        'strict': {
            'name': 'Строгая защита',
            'gif_limit': 2,
            'gif_time_window': 5,
            'sticker_limit': 3,
            'sticker_time_window': 10,
            'duplicate_text_limit': 2,
            'duplicate_text_window': 20,
            'mass_join_limit': 7,
            'mass_join_window': 60
        }
    }
    
    preset = presets[preset_type]
    
    # Применяем настройки
    await raid_protection_db.update_setting(chat.id, 'gif_limit', preset['gif_limit'])
    await raid_protection_db.update_setting(chat.id, 'gif_time_window', preset['gif_time_window'])
    await raid_protection_db.update_setting(chat.id, 'sticker_limit', preset['sticker_limit'])
    await raid_protection_db.update_setting(chat.id, 'sticker_time_window', preset['sticker_time_window'])
    await raid_protection_db.update_setting(chat.id, 'duplicate_text_limit', preset['duplicate_text_limit'])
    await raid_protection_db.update_setting(chat.id, 'duplicate_text_window', preset['duplicate_text_window'])
    await raid_protection_db.update_setting(chat.id, 'mass_join_limit', preset['mass_join_limit'])
    await raid_protection_db.update_setting(chat.id, 'mass_join_window', preset['mass_join_window'])
    
    # Возвращаемся в меню настройки
    await settings_open_raid_callback(callback)
    await callback.answer(f"✅ Применена {preset['name']}")


@dp.callback_query(F.data == "raid_mute_settings")
async def raid_mute_settings_callback(callback: types.CallbackQuery):
    """Настройка авто-мута защиты от рейдов"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat.id)
    current_mute = settings.get('auto_mute_duration', 0)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Кнопки для выбора времени мута
    mute_options = [0, 1, 5, 10, 15, 30, 60]
    
    for mute_time in mute_options:
        if mute_time == 0:
            text = "❌ Выключить"
        else:
            text = f"{mute_time} мин"
        
        if current_mute == mute_time:
            text = f"✅ {text}"
        
        builder.button(text=text, callback_data=f"raid_mute_{mute_time}")
    
    builder.button(text="🔙 Назад", callback_data="settings_open_raid")
    builder.adjust(3, 3, 1)
    
    if current_mute > 0:
        current_mute_text = f"{current_mute} мин"
    else:
        current_mute_text = "Выключено"
    
    settings_text = (
        "🔇 <b>Настройка авто-мута</b>\n\n"
        "Выберите время автоматического мута при обнаружении рейда.\n"
        "Бот будет автоматически мутить нарушителей до прихода модератора.\n\n"
        f"Текущее значение: <b>{current_mute_text}</b>"
    )
    
    await callback.message.edit_text(settings_text, parse_mode=ParseMode.HTML)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("raid_mute_"))
async def raid_mute_set_callback(callback: types.CallbackQuery):
    """Установить время авто-мута"""
    if not await _ensure_admin(callback):
        return
    
    chat = callback.message.chat
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat.id, user_id)
    if effective_rank not in [RANK_OWNER, RANK_ADMIN]:
        await callback.answer("❌ Только владелец или администратор могут изменить эту настройку!", show_alert=True)
        return
    
    # Получаем время мута из callback_data
    mute_time_str = callback.data.split("_")[2]
    mute_time = int(mute_time_str)
    
    await raid_protection_db.update_setting(chat.id, 'auto_mute_duration', mute_time)
    
    # Возвращаемся в меню настройки мута
    await raid_mute_settings_callback(callback)
    if mute_time == 0:
        await callback.answer("✅ Авто-мут выключен")
    else:
        await callback.answer(f"✅ Авто-мут установлен: {mute_time} минут")


@dp.callback_query(F.data == "settings_main")
async def settings_main_callback(callback: types.CallbackQuery):
    """Вернуться в главное меню настроек"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    warn_settings_context.discard((chat_id, callback.message.message_id))
    rank_settings_context.discard((chat_id, callback.message.message_id))
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    # network menu удален по требованию

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="settings_open_stat")
    builder.button(text="⚠️ Варны", callback_data="settings_open_warn")
    builder.button(text="🔰 Права/ранги", callback_data="settings_open_ranks")
    builder.button(text="🇷🇺 Префикс команд", callback_data="settings_open_ruprefix")
    builder.button(text="💡 Подсказки", callback_data="settings_open_hints")
    builder.button(text="🚪 Автодопуск", callback_data="settings_open_autojoin")
    builder.button(text="🛡️ Антирейд", callback_data="settings_open_raid")
    builder.button(text="🎬 Гифки", callback_data="settings_open_gifs")
    builder.button(text="🏆 Показ в топе", callback_data="settings_open_top")
    if effective_rank == RANK_OWNER:
        builder.button(text="⚙️ Инициализация прав", callback_data="settings_initperms")
    builder.button(text="🔙 Закрыть", callback_data="settings_close")
    builder.adjust(2, 2, 2, 1, 2, 1, 1)  # разбиение по рядам (Гифки и Показ в топе в одном ряду)

    text = (
        "⚙️ <b>Настройки чата</b>\n\n"
        f"👤 <b>Ваш ранг:</b> {RANK_NAMES.get(effective_rank, 'Неизвестно')}\n\n"
        "Выберите раздел настроек ниже:"
    )
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


@dp.message(Command("ap"))
@require_admin_rights
async def ap_command(message: Message):
    """Команда назначения ранга модератора"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только владелец/администраторы Telegram могут назначать
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ['creator', 'administrator']:
            msg = await message.answer("😑 Куда мы лезем?")
            asyncio.create_task(delete_message_after_delay(msg, 10))
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке прав для команды /ap: {e}")
        await message.answer("❌ Ошибка при проверке прав")
        return
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    rank = None
    
    if message.reply_to_message:
        # Формат: /ap 3 (при ответе на сообщение)
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code>\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)\n\n"
                    "Ранги: 1-Владелец, 2-Администратор, 3-Старший модератор, 4-Младший модератор",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        try:
            rank = int(args[1])
            target_user = message.reply_to_message.from_user
        except ValueError:
            await message.answer("❌ Ранг должен быть числом от 1 до 4")
            return
    else:
        # Формат: /ap @username 3
        if len(args) != 3:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code>\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)\n\n"
                    "Ранги: 1-Владелец, 2-Администратор, 3-Старший модератор, 4-Младший модератор",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        try:
            rank = int(args[2])
        except ValueError:
            await message.answer("❌ Ранг должен быть числом от 1 до 4")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code> или упоминание пользователя\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)\n\n"
                    "Ранги: 1-Владелец, 2-Администратор, 3-Старший модератор, 4-Младший модератор",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем корректность ранга
    if rank < 1 or rank > 4:
        await message.answer("❌ Ранг должен быть от 1 до 4")
        return
    
    # Проверяем, что не назначаем ранг самому себе
    if target_user.id == user_id:
        await message.answer("❌ Нельзя назначить ранг самому себе")
        return
    
    # Проверяем, что целевой пользователь не является ботом
    if target_user.is_bot:
        await message.answer("❌ Нельзя назначить ранг боту")
        return
    
    # Сохраняем информацию о пользователе в БД
    await db.add_user(
        user_id=target_user.id,
        username=target_user.username,
        first_name=target_user.first_name,
        last_name=target_user.last_name,
        is_bot=target_user.is_bot
    )
    
    # Назначаем ранг
    success = await db.assign_moderator(chat_id, target_user.id, rank, user_id)
    
    if success:
        rank_name = get_rank_name(rank)
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ <b>{username_display}</b> назначен на должность: <b>{rank_name}</b>",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("❌ Ошибка при назначении ранга")


@dp.message(Command("unap"))
@require_admin_rights
async def unap_command(message: Message):
    """Команда снятия ранга модератора"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только администраторы Telegram могут снимать
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ['creator', 'administrator']:
            if await should_show_hint(chat_id, user_id):
                await message.answer("❌ Недостаточно прав для снятия модераторов")
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке прав для команды /unap: {e}")
        await message.answer("❌ Ошибка при проверке прав")
        return
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /unap (при ответе на сообщение)
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code>\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /unap @username
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code>\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code> или упоминание пользователя\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем, что не снимаем ранг самому себе
    if target_user.id == user_id:
        await message.answer("❌ Нельзя снять ранг самому себе")
        return
    
    # Проверяем, что пользователь является модератором
    current_rank = await db.get_user_rank(chat_id, target_user.id)
    if current_rank is None:
        username_display = get_user_mention_html(target_user)
        await message.answer(f"❌ <b>{username_display}</b> не является модератором", parse_mode=ParseMode.HTML)
        return
    
    # Снимаем ранг
    success = await db.remove_moderator(chat_id, target_user.id)
    
    if success:
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ <b>{username_display}</b> снят с должности",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("❌ Ошибка при снятии ранга")


# (Удалены русские текстовые аналоги; теперь используется модуль command_aliases)


@dp.message(Command("staff"))
@require_admin_rights
async def staff_command(message: Message):
    """Команда отображения списка модераторов"""
    chat_id = message.chat.id
    
    # Получаем всех модераторов чата из БД
    moderators = await db.get_chat_moderators(chat_id)
    
    # Группируем модераторов по рангам
    ranks = {}
    
    # Добавляем владельца чата (исключение)
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        for admin in chat_admins:
            if admin.status == 'creator':
                user = admin.user
                if not user.is_bot:
                    # Проверяем, есть ли у владельца ранг в БД
                    db_rank = None
                    for mod in moderators:
                        if mod['user_id'] == user.id:
                            db_rank = mod['rank']
                            break
                    
                    # Владелец всегда имеет ранг владельца, независимо от БД
                    if RANK_OWNER not in ranks:
                        ranks[RANK_OWNER] = []
                    
                    user_info = {
                        'user_id': user.id,
                        'username': user.username,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'rank': RANK_OWNER
                    }
                    ranks[RANK_OWNER].append(user_info)
                break
    except Exception as e:
        logger.error(f"Ошибка при получении владельца чата {chat_id}: {e}")
    
    # Добавляем модераторов из БД бота
    for mod in moderators:
        rank = mod['rank']
        
        # Пропускаем владельца, если он уже добавлен выше
        if rank == RANK_OWNER:
            continue
        
        if rank not in ranks:
            ranks[rank] = []
        
        # Проверяем, не добавлен ли уже этот пользователь
        if not any(existing_mod['user_id'] == mod['user_id'] for existing_mod in ranks[rank]):
            ranks[rank].append(mod)
    
    if not ranks:
        await send_message_with_gif(
            message,
            "👥 <b>Модераторы чата</b>\n\n• Модераторы не назначены",
            "moderatorslist",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Формируем сообщение
    staff_text = "👥 <b>Модераторы чата</b>\n\n"
    
    # Эмодзи для рангов
    rank_emojis = {
        1: "👑",  # Владелец
        2: "⚜️",  # Администратор
        3: "🛡",  # Старший модератор
        4: "🔰"   # Младший модератор
    }
    
    # Сортируем ранги по возрастанию (1, 2, 3, 4)
    for rank in sorted(ranks.keys()):
        mods = ranks[rank]
        rank_name = get_rank_name(rank, len(mods))
        emoji = rank_emojis.get(rank, "👤")
        
        staff_text += f"{emoji} <b>{rank_name}:</b>\n"
        
        for mod in mods:
            # Формируем имя пользователя
            user_display = get_user_mention_html(mod)
            
            staff_text += f"• {user_display}\n"
        
        staff_text += "\n"
    
    await send_message_with_gif(message, staff_text, "moderatorslist", parse_mode=ParseMode.HTML)


async def build_hints_settings_panel(chat_id: int, current_mode: int | None = None):
    """Сформировать текст и клавиатуру для настройки подсказок команд."""
    if current_mode is None:
        current_mode = await db.get_hints_mode(chat_id)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    builder.add(InlineKeyboardButton(
        text="✅ Для всех" + (" ←" if current_mode == 0 else ""),
        callback_data="hints_mode_0"
    ))
    builder.add(InlineKeyboardButton(
        text="👤 Только для модераторов" + (" ←" if current_mode == 1 else ""),
        callback_data="hints_mode_1"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Выключены" + (" ←" if current_mode == 2 else ""),
        callback_data="hints_mode_2"
    ))
    builder.adjust(1)

    mode_descriptions = {
        0: "подсказки показываются всем пользователям",
        1: "подсказки показываются только модераторам",
        2: "подсказки выключены для всех"
    }

    text = (
        "🔧 <b>Настройка подсказок команд</b>\n\n"
        f"Текущий режим: <b>{mode_descriptions[current_mode]}</b>\n\n"
        "Выберите режим подсказок:\n"
        "• <b>Для всех</b> - подсказки показываются всем пользователям\n"
        "• <b>Только для модераторов</b> - подсказки только модераторам\n"
        "• <b>Выключены</b> - подсказки не показываются никому"
    )

    return text, builder.as_markup()


async def build_top_chats_settings_main(chat_id: int):
    """Главное меню настроек показа в топе с разделами"""
    settings = get_top_chat_settings(chat_id)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Разделы настроек
    builder.button(text="👁️ Видимость в топе", callback_data="top_settings_visibility")
    builder.button(text="🏷️ Отображение", callback_data="top_settings_display")
    builder.button(text="📊 Фильтры", callback_data="top_settings_filters")
    builder.adjust(1)
    
    # Кнопка назад
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1)
    
    visibility_descriptions = {
        "always": "показывать всегда (даже если частный)",
        "public_only": "показывать только если публичный",
        "never": "не показывать в топе"
    }
    
    show_in_top = settings.get('show_in_top', 'public_only')
    show_private_label = settings.get('show_private_label', False)
    min_activity = settings.get('min_activity_threshold', 0)
    
    text = (
        "🏆 <b>Настройки показа в топе</b>\n\n"
        f"<b>Видимость:</b> {visibility_descriptions.get(show_in_top, 'неизвестно')}\n"
        f"<b>Метка 'Частный':</b> {'Включена' if show_private_label else 'Выключена'}\n"
        f"<b>Минимум сообщений:</b> {min_activity}\n\n"
        "Выберите раздел настроек:"
    )
    
    return text, builder.as_markup()


async def build_top_chats_settings_visibility(chat_id: int, current_value: str = None):
    """Настройки видимости в топе"""
    if current_value is None:
        settings = get_top_chat_settings(chat_id)
        show_in_top = settings.get('show_in_top', 'public_only')
    else:
        show_in_top = current_value
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=("✅ " if show_in_top == "always" else "") + "Показывать всегда",
        callback_data="top_setting_visibility_always"
    )
    builder.button(
        text=("✅ " if show_in_top == "public_only" else "") + "Только публичные",
        callback_data="top_setting_visibility_public_only"
    )
    builder.button(
        text=("✅ " if show_in_top == "never" else "") + "Не показывать",
        callback_data="top_setting_visibility_never"
    )
    builder.adjust(1)
    
    builder.button(text="🔙 Назад", callback_data="settings_open_top")
    builder.adjust(1)
    
    visibility_descriptions = {
        "always": "показывать всегда (даже если частный)",
        "public_only": "показывать только если публичный",
        "never": "не показывать в топе"
    }
    
    text = (
        "👁️ <b>Видимость в топе</b>\n\n"
        f"Текущая настройка: <b>{visibility_descriptions.get(show_in_top, 'неизвестно')}</b>\n\n"
        "Выберите режим видимости:"
    )
    
    return text, builder.as_markup()


async def build_top_chats_settings_display(chat_id: int):
    """Настройки отображения"""
    settings = get_top_chat_settings(chat_id)
    show_private_label = settings.get('show_private_label', False)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=("✅ " if show_private_label else "") + "Метка 'Частный': " + ("Вкл." if show_private_label else "Выкл."),
        callback_data="top_setting_private_label_toggle"
    )
    builder.adjust(1)
    
    builder.button(text="🔙 Назад", callback_data="settings_open_top")
    builder.adjust(1)
    
    text = (
        "🏷️ <b>Настройки отображения</b>\n\n"
        f"<b>Метка 'Частный':</b> {'Включена' if show_private_label else 'Выключена'}\n\n"
        "Если включено, рядом с частными чатами в топе будет отображаться метка 🔒"
    )
    
    return text, builder.as_markup()


async def build_top_chats_settings_filters(chat_id: int):
    """Настройки фильтров"""
    settings = get_top_chat_settings(chat_id)
    min_activity = settings.get('min_activity_threshold', 0)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"Минимум сообщений: {min_activity}",
        callback_data="top_setting_min_activity_menu"
    )
    builder.adjust(1)
    
    builder.button(text="🔙 Назад", callback_data="settings_open_top")
    builder.adjust(1)
    
    text = (
        "📊 <b>Фильтры</b>\n\n"
        f"<b>Минимум сообщений:</b> {min_activity}\n\n"
        "Установите минимальное количество сообщений, необходимое для показа чата в топе.\n"
        "Если установлено 0, ограничений нет."
    )
    
    return text, builder.as_markup()


@dp.callback_query(F.data == "settings_open_top")
async def settings_open_top_callback(callback: types.CallbackQuery):
    """Открыть главное меню настроек показа в топе"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    try:
        text, markup = await build_top_chats_settings_main(chat_id)
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_top_callback в чате {chat_id}: {e}")
        await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "top_settings_visibility")
async def top_settings_visibility_callback(callback: types.CallbackQuery):
    """Открыть настройки видимости"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    try:
        text, markup = await build_top_chats_settings_visibility(chat_id)
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        # Обрабатываем ошибку "message is not modified"
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            logger.error(f"Ошибка top_settings_visibility_callback в чате {chat_id}: {e}")
            await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "top_settings_display")
async def top_settings_display_callback(callback: types.CallbackQuery):
    """Открыть настройки отображения"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    try:
        text, markup = await build_top_chats_settings_display(chat_id)
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        # Обрабатываем ошибку "message is not modified"
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            logger.error(f"Ошибка top_settings_display_callback в чате {chat_id}: {e}")
            await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data == "top_settings_filters")
async def top_settings_filters_callback(callback: types.CallbackQuery):
    """Открыть настройки фильтров"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    try:
        text, markup = await build_top_chats_settings_filters(chat_id)
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        # Обрабатываем ошибку "message is not modified"
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            logger.error(f"Ошибка top_settings_filters_callback в чате {chat_id}: {e}")
            await callback.answer("❌ Ошибка при загрузке настроек", show_alert=True)


@dp.callback_query(F.data.startswith("top_setting_visibility_"))
async def top_setting_visibility_callback(callback: types.CallbackQuery):
    """Обработчик изменения настройки видимости в топе"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    # Извлекаем значение после "top_setting_visibility_"
    visibility = callback.data.replace("top_setting_visibility_", "")  # always, public_only, или never
    
    # Проверяем текущее значение перед изменением
    current_settings = get_top_chat_settings(chat_id)
    current_visibility = current_settings.get('show_in_top', 'public_only')
    
    # Если значение не изменилось, просто отвечаем на callback
    if current_visibility == visibility:
        await callback.answer("Эта настройка уже выбрана")
        return
    
    success = set_top_chat_setting(chat_id, 'show_in_top', visibility)
    if success:
        try:
            # Используем сохраненное значение напрямую, без чтения из файла
            text, markup = await build_top_chats_settings_visibility(chat_id, current_value=visibility)
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            await callback.answer("✅ Настройка изменена")
        except Exception as e:
            # Обрабатываем ошибку "message is not modified"
            if "message is not modified" in str(e):
                await callback.answer("✅ Настройка изменена")
            else:
                logger.error(f"Ошибка при обновлении сообщения в top_setting_visibility_callback: {e}")
                await callback.answer("✅ Настройка изменена")
    else:
        await callback.answer("❌ Ошибка при сохранении настройки", show_alert=True)


@dp.callback_query(F.data == "top_setting_private_label_toggle")
async def top_setting_private_label_callback(callback: types.CallbackQuery):
    """Обработчик переключения метки 'Частный'"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = get_top_chat_settings(chat_id)
    current_value = settings.get('show_private_label', False)
    new_value = not current_value
    
    success = set_top_chat_setting(chat_id, 'show_private_label', new_value)
    if success:
        try:
            text, markup = await build_top_chats_settings_display(chat_id)
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            await callback.answer("✅ Настройка изменена")
        except Exception as e:
            # Обрабатываем ошибку "message is not modified"
            if "message is not modified" in str(e):
                await callback.answer("✅ Настройка изменена")
            else:
                logger.error(f"Ошибка при обновлении сообщения в top_setting_private_label_callback: {e}")
                await callback.answer("✅ Настройка изменена")
    else:
        await callback.answer("❌ Ошибка при сохранении настройки", show_alert=True)


@dp.callback_query(F.data == "top_setting_min_activity_menu")
async def top_setting_min_activity_menu_callback(callback: types.CallbackQuery):
    """Показать меню выбора минимального порога активности"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = get_top_chat_settings(chat_id)
    current_threshold = settings.get('min_activity_threshold', 0)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    # Варианты порогов активности
    thresholds = [0, 10, 50, 100, 200, 500, 1000, 2000, 5000]
    for threshold in thresholds:
        text = f"{threshold}" if threshold > 0 else "Без ограничений"
        if current_threshold == threshold:
            text = f"✅ {text}"
        builder.button(
            text=text,
            callback_data=f"top_setting_min_activity_{threshold}"
        )
    
    builder.button(text="🔙 Назад", callback_data="top_settings_filters")
    builder.adjust(3, 3, 3, 1)
    
    text = (
        f"🏆 <b>Минимальный порог активности</b>\n\n"
        f"Текущее значение: <b>{current_threshold}</b> сообщений\n\n"
        "Выберите минимальное количество сообщений, необходимое для показа чата в топе.\n"
        "Если установлено 0, ограничений нет."
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("top_setting_min_activity_"))
async def top_setting_min_activity_callback(callback: types.CallbackQuery):
    """Обработчик изменения минимального порога активности"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    try:
        threshold = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Ошибка при обработке значения", show_alert=True)
        return
    
    # Проверяем текущее значение перед изменением
    current_settings = get_top_chat_settings(chat_id)
    current_threshold = current_settings.get('min_activity_threshold', 0)
    
    # Если значение не изменилось, просто отвечаем на callback
    if current_threshold == threshold:
        await callback.answer("Эта настройка уже выбрана")
        return
    
    success = set_top_chat_setting(chat_id, 'min_activity_threshold', threshold)
    if success:
        try:
            # Возвращаемся в меню выбора порога
            await top_setting_min_activity_menu_callback(callback)
            await callback.answer("✅ Настройка изменена")
        except Exception as e:
            # Обрабатываем ошибку "message is not modified"
            if "message is not modified" in str(e):
                await callback.answer("✅ Настройка изменена")
            else:
                logger.error(f"Ошибка при обновлении сообщения в top_setting_min_activity_callback: {e}")
                await callback.answer("✅ Настройка изменена")
    else:
        await callback.answer("❌ Ошибка при сохранении настройки", show_alert=True)


@dp.message(Command("hintsconfig"))
@require_admin_rights
@require_bot_admin_rights
async def hintsconfig_command(message: Message):
    """Команда настройки режима подсказок"""
    chat_id = message.chat.id

    text, markup = await build_hints_settings_panel(chat_id)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@dp.message(Command("mute"))
@require_admin_rights
async def mute_command(message: Message):
    """Команда мута пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_mute = await check_permission(chat_id, user_id, 'can_mute', lambda r: r <= 4)
    if not can_mute:
        sent_message = await message.answer("🫠 Ты хочешь заставить кого-то замолчать, но власть — не то, что можно взять просто так. Молчание порождается авторитетом, а не желанием заставить замолчать. Чтобы даровать молчание, нужно самому обладать голосом в этом чате.")
        
        # Удаляем сообщение через 5 секунд
        async def delete_message_after_delay():
            await asyncio.sleep(5)
            try:
                await sent_message.delete()
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение: {e}")
        
        asyncio.create_task(delete_message_after_delay())
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    time_str = None
    
    if message.reply_to_message:
        # Формат: /mute 10 часов (при ответе на сообщение)
        if len(args) < 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                    "• <code>/mute @username 10 часов</code>\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/mute 10 часов\nНарушение правил</code>\n\n"
                    "Примеры времени:\n"
                    "• 30 минут\n"
                    "• 2 часа\n"
                    "• 5 дней\n"
                    "• 60 секунд",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
        time_str = ' '.join(args[1:])  # Объединяем все аргументы после команды
    else:
        # Формат: /mute @username 10 часов
        if len(args) < 3:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                    "• <code>/mute @username 10 часов</code>\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/mute @username 10 часов\nНарушение правил</code>\n\n"
                    "Примеры времени:\n"
                    "• 30 минут\n"
                    "• 2 часа\n"
                    "• 5 дней\n"
                    "• 60 секунд",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                    "• <code>/mute @username 10 часов</code> или упоминание пользователя\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/mute @username 10 часов\nНарушение правил</code>\n\n"
                    "Примеры времени:\n"
                    "• 30 минут\n"
                    "• 2 часа\n"
                    "• 5 дней\n"
                    "• 60 секунд",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
        
        time_str = ' '.join(args[2:])  # Объединяем все аргументы после username
    
    # Парсим время
    duration_seconds = parse_mute_duration(time_str)
    if duration_seconds is None:
        await message.answer(
            "❌ <b>Некорректный формат времени</b>\n\n"
            "Примеры правильного формата:\n"
            "• 30 минут\n"
            "• 2 часа\n"
            "• 5 дней\n"
            "• 60 секунд\n\n"
            "Поддерживаемые единицы:\n"
            "• Секунды: сек, с, секунд\n"
            "• Минуты: мин, м, минут\n"
            "• Часы: ч, часов, час\n"
            "• Дни: д, дней, день",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем ограничения времени
    if duration_seconds <= 0:
        await message.answer("❌ Время мута должно быть больше 0")
        return
    
    max_duration = 366 * 24 * 3600  # 366 дней в секундах
    if duration_seconds > max_duration:
        await message.answer("❌ Максимальное время мута: 366 дней")
        return
    
    # Проверяем, что не мутим самого себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя замутить самого себя")
        return
    
    # Проверяем, что целевой пользователь не является ботом
    if target_user.is_bot:
        await message.answer("❌ Нельзя замутить бота")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:  # Нельзя мутить владельца или администратора
        await message.answer("❌ Нельзя замутить владельца или администратора")
        return
    
    # Проверяем, что модератор может мутить этого пользователя
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя замутить пользователя с равным или выше рангом")
        return
    
    # Вычисляем время окончания мута
    from datetime import datetime, timedelta, timezone
    
    # Используем UTC время
    mute_until_dt = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    # Конвертируем в Unix timestamp (секунды с 1 января 1970 UTC)
    mute_until_timestamp = int(mute_until_dt.timestamp())
    
    logger.info(f"Мутим пользователя {target_user.id} до {mute_until_dt} (timestamp: {mute_until_timestamp})")
    
    try:
        # Применяем мут
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=mute_until_dt
        )
        
        # Сначала деактивируем все активные муты для этого пользователя (перезапись мута)
        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
        for mute in active_mutes:
            if mute['user_id'] == target_user.id:
                await moderation_db.deactivate_punishment(mute['id'])
                logger.info(f"Деактивирован старый мут {mute['id']} для пользователя {target_user.id}")

        # Записываем новое наказание в базу данных модерации
        await moderation_db.add_punishment(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            punishment_type="mute",
            reason=reason,
            duration_seconds=duration_seconds,
            expiry_date=mute_until_dt.isoformat(),
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('mute', duration_seconds)
        await reputation_db.add_recent_punishment(target_user.id, 'mute', duration_seconds)
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Форматируем время окончания мута
        mute_until_str = mute_until_dt.strftime("%d.%m.%Y %H:%M")
        
        # Формируем сообщение с причиной
        message_text = f"🔊 Участник <b>{username_display}</b> был(а) замучен(а) на <i>{time_str}</i>\n"
        if reason:
            message_text += f"📝 <b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "mute", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при применении мута пользователю {target_user.id}: {e}")
        await message.answer("❌ Ошибка при применении мута")


@dp.message(Command("kick"))
@require_admin_rights
async def kick_command(message: Message):
    """Команда кика пользователя из чата"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только старшие модераторы и выше могут кикать
    can_kick = await check_permission(chat_id, user_id, 'can_kick', lambda r: r <= 3)
    if not can_kick:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /kick (при ответе на сообщение)
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick @username</code>\n"
                    "• <code>/kick</code> (при ответе на сообщение)\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/kick\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /kick @username
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick @username</code>\n"
                    "• <code>/kick</code> (при ответе на сообщение)\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/kick @username\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick</code> (при ответе на сообщение)\n"
                    "• <code>/kick @username</code> или упоминание пользователя\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/kick @username\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверки
    if target_user.id == bot.id:
        await message.answer("😐 Себя кикать нельзя")
        return
    
    if target_user.id == user_id:
        await message.answer("😐 Себя кикать нельзя")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:  # Нельзя кикать владельца или администратора
        await message.answer("😑 Нельзя кикнуть владельца или администратора")
        return
    
    try:
        # Добавляем в черный список и сразу удаляем (кик)
        await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Разбаниваем пользователя, чтобы он мог вернуться в чат
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('kick')
        await reputation_db.add_recent_punishment(target_user.id, 'kick')
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение с причиной
        message_text = f"💨 Участник <b>{username_display}</b> был(а) исключен(а) из чата\n"
        if reason:
            message_text += f"📝 <b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "kick", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при кике пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при исключении пользователя")


@dp.message(Command("warn"))
@require_admin_rights
async def warn_command(message: Message):
    """Команда выдачи предупреждения пользователю"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_warn = await check_permission(chat_id, user_id, 'can_warn', lambda r: r <= 4)
    if not can_warn:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /warn (при ответе на сообщение)
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code>\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/warn\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /warn @username или mention
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code> или упоминание пользователя\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/warn @username\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code> или упоминание пользователя\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/warn @username\nНарушение правил</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем, что пользователь не бот
    if target_user.is_bot:
        await message.answer("❌ Нельзя выдать предупреждение боту")
        return
    
    # Проверяем, что пользователь не сам себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя выдать предупреждение самому себе")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя выдать предупреждение пользователю с равным или более высоким рангом")
        return
    
    try:
        # Добавляем варн в базу данных
        await moderation_db.add_warn(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            reason=reason,
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('warn')
        await reputation_db.add_recent_punishment(target_user.id, 'warn')
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Получаем текущее количество варнов
        warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        
        # Получаем настройки варнов для чата
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Проверяем, достигнут ли лимит варнов
        if warn_count >= warn_limit:
            # Лимит достигнут - применяем наказание
            punishment_type = warn_settings['punishment_type']
            
            if punishment_type == 'kick':
                # Кикаем пользователя
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
                await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
                
                # Обновляем репутацию
                penalty = reputation_db.calculate_reputation_penalty('kick')
                await reputation_db.add_recent_punishment(target_user.id, 'kick')
                await reputation_db.update_reputation(target_user.id, penalty)
                
                # Очищаем все варны пользователя
                await moderation_db.clear_user_warns(chat_id, target_user.id)
                
                # Сообщение в чат
                message_text = (
                    f"🚫 Участник <b>{username_display}</b> достиг(ла) лимита предупреждений ({warn_limit}/{warn_limit})\n"
                    f"💨 Участник был(а) исключен(а) из чата\n"
                    f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                )
                await send_message_with_gif(message, message_text, "kick", parse_mode=ParseMode.HTML)
                
                # Уведомление в ЛС пользователю
                try:
                    chat_info = await bot.get_chat(chat_id)
                    chat_title = chat_info.title or "Неизвестный чат"
                    await bot.send_message(
                        target_user.id,
                        f"⚠️ Вы достигли лимита предупреждений в чате \"{chat_title}\"\n"
                        f"Вы были исключены из чата.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления пользователю {target_user.id}: {e}")
            
            elif punishment_type == 'mute':
                # Мутим пользователя
                mute_duration = warn_settings['mute_duration'] or 3600  # По умолчанию 1 час
                mute_until = datetime.now() + timedelta(seconds=mute_duration)
                
                # Применяем мут
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    ),
                    until_date=mute_until
                )
                
                # Записываем наказание в базу данных модерации
                await moderation_db.add_punishment(
                    chat_id=chat_id,
                    user_id=target_user.id,
                    moderator_id=user_id,
                    punishment_type="mute",
                    reason="Достигнут лимит предупреждений",
                    duration_seconds=mute_duration,
                    expiry_date=mute_until.isoformat(),
                    user_username=target_user.username,
                    user_first_name=target_user.first_name,
                    user_last_name=target_user.last_name,
                    moderator_username=message.from_user.username,
                    moderator_first_name=message.from_user.first_name,
                    moderator_last_name=message.from_user.last_name
                )
                
                # Очищаем все варны пользователя
                await moderation_db.clear_user_warns(chat_id, target_user.id)
                
                # Форматируем время мута
                time_str = format_mute_duration(mute_duration)
                
                # Сообщение в чат
                message_text = (
                    f"🚫 Участник <b>{username_display}</b> достиг(ла) лимита предупреждений ({warn_limit}/{warn_limit})\n"
                    f"🔇 Участник был(а) замучен(а) на <i>{time_str}</i>\n"
                    f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                )
                await send_message_with_gif(message, message_text, "mute", parse_mode=ParseMode.HTML)
                
                # Уведомление в ЛС пользователю
                try:
                    chat_info = await bot.get_chat(chat_id)
                    chat_title = chat_info.title or "Неизвестный чат"
                    await bot.send_message(
                        target_user.id,
                        f"⚠️ Вы достигли лимита предупреждений в чате \"{chat_title}\"\n"
                        f"Вы были замучены на {time_str}.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления пользователю {target_user.id}: {e}")
        else:
            # Лимит не достигнут - просто сообщаем о варне
            message_text = f"⚠️ Участник <b>{username_display}</b> получил(а) предупреждение ({warn_count}/{warn_limit})\n"
            if reason:
                message_text += f"📝 <b>Причина:</b> <i>{reason}</i>\n"
            message_text += f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
            
            await send_message_with_gif(message, message_text, "warn", parse_mode=ParseMode.HTML)
            
            # Уведомление в ЛС пользователю
            try:
                chat_info = await bot.get_chat(chat_id)
                chat_title = chat_info.title or "Неизвестный чат"
                ls_message = f"⚠️ Вы получили предупреждение в чате \"{chat_title}\"\n"
                if reason:
                    ls_message += f"📝 <b>Причина:</b> <i>{reason}</i>\n"
                ls_message += f"Количество предупреждений: {warn_count}/{warn_limit}"
                
                await bot.send_message(
                    target_user.id,
                    ls_message,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {target_user.id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при выдаче предупреждения пользователю {target_user.id}: {e}")
        await message.answer("❌ Ошибка при выдаче предупреждения")


@dp.message(Command("unwarn"))
@require_admin_rights
async def unwarn_command(message: Message):
    """Команда снятия предупреждения пользователю"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_unwarn = await check_permission(chat_id, user_id, 'can_unwarn', lambda r: r <= 4)
    if not can_unwarn:
        await send_access_denied_message(message, chat_id, user_id)
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /unwarn (при ответе на сообщение)
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /unwarn @username
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем, что пользователь не бот
    if target_user.is_bot:
        await message.answer("❌ Нельзя снять предупреждение боту")
        return
    
    # Проверяем, что пользователь не сам себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя снять предупреждение самому себе")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя снять предупреждение пользователю с равным или более высоким рангом")
        return
    
    try:
        # Проверяем, есть ли активные варны у пользователя
        warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        if warn_count == 0:
            await message.answer("❌ У пользователя нет активных предупреждений")
            return
        
        # Снимаем последний варн
        success = await moderation_db.remove_warn(chat_id, target_user.id)
        if not success:
            await message.answer("❌ Ошибка при снятии предупреждения")
            return
        
        # Получаем новое количество варнов
        new_warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        
        # Получаем настройки варнов для чата
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ У участника(а) <b>{username_display}</b> снято предупреждение ({new_warn_count}/{warn_limit})\n"
            f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при снятии предупреждения пользователю {target_user.id}: {e}")
        await message.answer("❌ Ошибка при снятии предупреждения")


@dp.message(Command("warns"))
@require_admin_rights
async def warns_command(message: Message):
    """Команда просмотра предупреждений пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /warns (при ответе на сообщение)
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /warns @username
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            await message.answer(
                "❌ <b>Пользователь не найден</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code> или упоминание пользователя",
                parse_mode=ParseMode.HTML
            )
            return
    
    try:
        # Получаем активные варны пользователя
        active_warns = await moderation_db.get_user_warns(chat_id, target_user.id, active_only=True)
        
        # Получаем все варны (включая неактивные) для истории
        all_warns = await moderation_db.get_user_warns(chat_id, target_user.id, active_only=False)
        
        # Получаем настройки варнов для чата
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение
        warn_count = len(active_warns)
        message_text = f"📊 <b>Предупреждения участника {username_display}:</b> {warn_count}/{warn_limit}\n\n"
        
        if all_warns:
            message_text += "<b>История предупреждений:</b>\n"
            for i, warn in enumerate(all_warns, 1):
                # Форматируем дату
                try:
                    from datetime import datetime
                    warn_date = datetime.fromisoformat(warn['warn_date'])
                    date_str = warn_date.strftime("%d.%m.%Y %H:%M")
                except:
                    date_str = warn['warn_date']
                
                # Формируем имя модератора
                moderator_name = warn['moderator_first_name'] or warn['moderator_username'] or "Неизвестно"
                
                # Статус варна
                status = "✅" if warn['is_active'] else "❌"
                
                message_text += f"{i}. {status} {date_str}\n"
                if warn.get('reason'):
                    message_text += f"   📝 Причина: {warn['reason']}\n"
                message_text += f"   👮 Модератор: {moderator_name}\n"
        else:
            message_text += "📝 История предупреждений пуста"
        
        await message.answer(message_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при получении предупреждений пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при получении предупреждений")


@dp.message(Command("warnconfig"))
@require_admin_rights
@require_bot_admin_rights
async def warnconfig_command(message: Message):
    """Команда настройки системы варнов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только администраторы и выше
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
        return
    
    try:
        # Получаем текущие настройки варнов
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        
        # Формируем сообщение с настройками
        mute_time_text = "Не установлено"
        if warn_settings['mute_duration']:
            mute_time_text = format_mute_duration(warn_settings['mute_duration'])
        
        if warn_settings['punishment_type'] == 'kick':
            punishment_text = "Кик"
        elif warn_settings['punishment_type'] == 'mute':
            punishment_text = "Мут"
        elif warn_settings['punishment_type'] == 'ban':
            punishment_text = "Бан"
        else:
            punishment_text = "Неизвестно"
        
        # Формируем сообщение в зависимости от типа наказания
        if warn_settings['punishment_type'] == 'mute':
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}\n"
                f"⏰ <b>Время мута:</b> {mute_time_text}"
            )
        elif warn_settings['punishment_type'] == 'ban':
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}\n"
                f"⏰ <b>Время бана:</b> {mute_time_text}"
            )
        else:
            message_text = (
                f"⚙️ <b>Настройки системы варнов</b>\n\n"
                f"🔢 <b>Лимит варнов:</b> {warn_settings['warn_limit']}\n"
                f"⚡ <b>Наказание:</b> {punishment_text}"
            )
        
        # Создаем кнопки
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        builder.button(text="🔢 Изменить лимит", callback_data="warnconfig_limit")
        builder.button(text="⚡ Изменить наказание", callback_data="warnconfig_punishment")
        
        if warn_settings['punishment_type'] == 'mute':
            builder.button(text="⏰ Изменить время мута", callback_data="warnconfig_mutetime")
        elif warn_settings['punishment_type'] == 'ban':
            builder.button(text="⏰ Изменить время бана", callback_data="warnconfig_bantime")
        
        builder.adjust(1)
        
        await message.answer(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при получении настроек варнов для чата {chat_id}: {e}")
        await message.answer("❌ Ошибка при получении настроек варнов")


@dp.message(Command("initperms"))
@require_admin_rights
async def initperms_command(message: Message):
    """Команда инициализации прав по умолчанию"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только владелец
    caller_rank = await get_effective_rank(chat_id, user_id)
    if caller_rank != 1:
        await send_access_denied_message(message, chat_id, user_id)
        return
    
    try:
        success = await db.initialize_rank_permissions(chat_id)
        if success:
            await message.answer("✅ Права по умолчанию инициализированы для всех рангов")
        else:
            await message.answer("❌ Ошибка при инициализации прав")
    except Exception as e:
        logger.error(f"Ошибка при инициализации прав в чате {chat_id}: {e}")
        await message.answer("❌ Ошибка при инициализации прав")




@dp.message(Command("statconfig"))
@require_admin_rights
@require_bot_admin_rights
async def statconfig_command(message: Message):
    """Команда настройки статистики чата"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только владелец и администраторы (ранг 1-2)
    caller_rank = await get_effective_rank(chat_id, user_id)
    if caller_rank > 2:
        await send_access_denied_message(message, chat_id, user_id)
        return
    
    try:
        # Получаем текущие настройки
        stat_settings = await db.get_chat_stat_settings(chat_id)
        
        # Создаем меню
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        # Кнопка статистики
        stats_icon = "✅" if stat_settings['stats_enabled'] else "❌"
        builder.button(text=f"{stats_icon} Статистика включена", callback_data="statconfig_toggle_stats")
        
        # Кнопка учета медиа
        media_icon = "✅" if stat_settings.get('count_media', True) else "❌"
        builder.button(text=f"{media_icon} Считать медиа", callback_data="statconfig_toggle_media")
        
        # Кнопка профиля
        profile_icon = "✅" if stat_settings.get('profile_enabled', True) else "❌"
        builder.button(text=f"{profile_icon} Команда профиля", callback_data="statconfig_toggle_profile")
        
        builder.adjust(1)
        
        # Кнопка закрытия
        builder.button(text="🔙 Закрыть", callback_data="statconfig_close")
        
        message_text = "📊 <b>Настройки статистики</b>\n\n"
        message_text += f"📈 Статистика: {'включена' if stat_settings['stats_enabled'] else 'отключена'}\n"
        message_text += f"🖼️ Учет медиа: {'включен' if stat_settings.get('count_media', True) else 'выключен'}\n"
        message_text += f"👤 Команда профиля: {'включена' if stat_settings.get('profile_enabled', True) else 'отключена'}\n"
        message_text += f"🖼️ Учет медиа: {'включен' if stat_settings.get('count_media', True) else 'выключен'}\n"
        message_text += f"⏱️ Временной интервал: 1 секунда (все сообщения)\n\n"
        message_text += "Выберите настройку для изменения:"
        
        await message.answer(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек статистики для чата {chat_id}: {e}")
        await message.answer("❌ Ошибка при получении настроек статистики")


@dp.message(Command("reputation", "rep"))
async def reputation_command(message: Message):
    """Команда просмотра репутации пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Определяем целевого пользователя
    target_user = None
    
    if message.reply_to_message:
        # При ответе на сообщение
        target_user = message.reply_to_message.from_user
    else:
        # Парсим аргументы
        args = message.text.split()
        if len(args) == 2:
            # Формат: /reputation @username или упоминание
            target_user = await parse_user_from_args(message, args, 1)
            if not target_user:
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/reputation</code> - показать свою репутацию\n"
                    "• <code>/reputation @username</code> или упоминание - показать репутацию пользователя\n"
                    "• <code>/reputation</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
                return
        elif len(args) == 1:
            # Показываем свою репутацию
            target_user = message.from_user
        else:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/reputation</code> - показать свою репутацию\n"
                "• <code>/reputation @username</code> - показать репутацию пользователя\n"
                "• <code>/reputation</code> (при ответе на сообщение)",
                parse_mode=ParseMode.HTML
            )
            return
    
    if not target_user:
        await message.answer("❌ Пользователь не найден")
        return
    
    try:
        # Получаем репутацию
        reputation = await reputation_db.get_user_reputation(target_user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        progress_bar = get_reputation_progress_bar(reputation)
        
        # Получаем статистику наказаний за последние 3 дня
        stats = await reputation_db.get_recent_punishment_stats(target_user.id, days=3)
        
        # Получаем историю наказаний
        recent_punishments = await reputation_db.get_recent_punishments(target_user.id, days=3)
        
        # Формируем имя пользователя
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение
        message_text = f"🎯 <b>Репутация:</b> {reputation}/100\n"
        message_text += f"[{progress_bar}] {reputation_emoji}\n\n"
        
        message_text += f"👤 <b>Пользователь:</b> {username_display}\n\n"
        
        message_text += "📋 <b>Наказания (последние 3 дня):</b>\n"
        message_text += f"⚠️ Варны: {stats['warn']}\n"
        message_text += f"🔇 Муты: {stats['mute']}\n"
        message_text += f"💨 Кики: {stats['kick']}\n"
        message_text += f"🚫 Баны: {stats['ban']}\n\n"
        
        if recent_punishments:
            message_text += "📜 <b>История наказаний:</b>\n"
            for punishment in recent_punishments[:5]:  # Показываем только последние 5
                try:
                    date_obj = datetime.fromisoformat(punishment['punishment_date'])
                    date_str = date_obj.strftime('%d.%m %H:%M')
                except:
                    date_str = punishment['punishment_date']
                
                punishment_type = punishment['punishment_type']
                duration = punishment['duration_seconds']
                
                # Форматируем тип наказания
                type_emoji = {
                    'warn': '',
                    'mute': '',
                    'kick': '',
                    'ban': ''
                }.get(punishment_type, '❓')
                
                duration_text = ""
                if duration:
                    duration_text = f" ({format_mute_duration(duration)})"
                
                message_text += f"{type_emoji} {date_str} - {punishment_type}{duration_text}\n"
        else:
            message_text += "📜 <b>История наказаний:</b> Нет нарушений за последние 3 дня ✅"
        
        await message.answer(message_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при получении репутации пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при получении информации о репутации")


@dp.message(Command("mentionping"))
async def mentionping_command(message: Message):
    """Включить кликабельные упоминания (ping) в статистике (глобально для пользователя)"""
    user_id = message.from_user.id
    
    try:
        success = await db.set_user_mention_ping_enabled(user_id, True)
        if success:
            await message.answer(
                "✅ <b>Кликабельные упоминания включены</b>\n\n"
                "Теперь ваше имя в статистике будет кликабельным (ping) во всех чатах.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("❌ Ошибка при изменении настройки")
    except Exception as e:
        logger.error(f"Ошибка при включении mention ping для пользователя {user_id}: {e}")
        await message.answer("❌ Ошибка при изменении настройки")


@dp.message(Command("unmentionping"))
async def unmentionping_command(message: Message):
    """Выключить кликабельные упоминания (ping) в статистике (глобально для пользователя)"""
    user_id = message.from_user.id
    
    try:
        success = await db.set_user_mention_ping_enabled(user_id, False)
        if success:
            await message.answer(
                "🔕 <b>Кликабельные упоминания выключены</b>\n\n"
                "Теперь ваше имя в статистике будет некликабельным (без ping) во всех чатах.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("❌ Ошибка при изменении настройки")
    except Exception as e:
        logger.error(f"Ошибка при выключении mention ping для пользователя {user_id}: {e}")
        await message.answer("❌ Ошибка при изменении настройки")


@dp.callback_query(F.data.startswith("statconfig_"))
async def statconfig_callback(callback: CallbackQuery):
    """Обработчик кнопок настроек статистики"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права - только владелец и администраторы (ранг 1-2)
    caller_rank = await get_effective_rank(chat_id, user_id)
    if caller_rank > 2:
        await answer_access_denied_callback(callback)
        return
    
    # Проверяем кулдаун
    if not check_cooldown(user_id):
        await callback.answer("⏳ Подождите 3 секунды перед следующим действием", show_alert=True)
        return
    
    try:
        action = callback.data.split("_", 1)[1]  # Получаем действие после "statconfig_"
        
        if action == "toggle_stats":
            # Переключаем статистику
            current_settings = await db.get_chat_stat_settings(chat_id)
            new_enabled = not current_settings['stats_enabled']
            
            success = await db.set_chat_stats_enabled(chat_id, new_enabled)
            if success:
                status = "включена" if new_enabled else "отключена"
                logger.info(f"Настройки статистики для чата {chat_id}: stats_enabled={new_enabled}")
                await callback.answer(f"📊 Статистика {status}")
            else:
                await callback.answer("❌ Ошибка при изменении настройки", show_alert=True)
                return
        elif action == "toggle_media":
            current_settings = await db.get_chat_stat_settings(chat_id)
            new_enabled = not current_settings.get('count_media', True)
            success = await db.set_chat_stats_count_media(chat_id, new_enabled)
            if success:
                status = "включен" if new_enabled else "выключен"
                logger.info(f"Настройки статистики для чата {chat_id}: count_media={new_enabled}")
                await callback.answer(f"🖼️ Учет медиа {status}")
            else:
                await callback.answer("❌ Ошибка при изменении настройки", show_alert=True)
                return
        elif action == "toggle_profile":
            current_settings = await db.get_chat_stat_settings(chat_id)
            new_enabled = not current_settings.get('profile_enabled', True)
            success = await db.set_chat_stats_profile_enabled(chat_id, new_enabled)
            if success:
                status = "включена" if new_enabled else "отключена"
                logger.info(f"Настройки статистики для чата {chat_id}: profile_enabled={new_enabled}")
                await callback.answer(f"👤 Команда профиля {status}")
            else:
                await callback.answer("❌ Ошибка при изменении настройки", show_alert=True)
                return
        
        
        elif action == "close":
            # Закрываем меню
            await callback.message.delete()
            await callback.answer()
            return
        
        # Обновляем меню
        stat_settings = await db.get_chat_stat_settings(chat_id)
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        # Кнопка статистики
        stats_icon = "✅" if stat_settings['stats_enabled'] else "❌"
        builder.button(text=f"{stats_icon} Статистика включена", callback_data="statconfig_toggle_stats")
        
        # Кнопка медиа
        media_icon = "✅" if stat_settings.get('count_media', True) else "❌"
        builder.button(text=f"{media_icon} Считать медиа", callback_data="statconfig_toggle_media")
        
        # Кнопка профиля
        profile_icon = "✅" if stat_settings.get('profile_enabled', True) else "❌"
        builder.button(text=f"{profile_icon} Команда профиля", callback_data="statconfig_toggle_profile")
        
        builder.adjust(1)
        
        # Кнопка закрытия
        builder.button(text="🔙 Закрыть", callback_data="statconfig_close")
        
        message_text = "📊 <b>Настройки статистики</b>\n\n"
        message_text += f"📈 Статистика: {'включена' if stat_settings['stats_enabled'] else 'отключена'}\n"
        message_text += f"⏱️ Временной интервал: 1 секунда (все сообщения)\n\n"
        message_text += "Выберите настройку для изменения:"
        
        await callback.message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке callback настроек статистики: {e}")
        await callback.answer("❌ Ошибка при изменении настройки", show_alert=True)


@dp.message(Command("rankconfig"))
@require_admin_rights
@require_bot_admin_rights
async def rankconfig_command(message: Message):
    """Команда настройки прав рангов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - по умолчанию только владелец, но можно настроить
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 1)
    if not can_config_ranks:
            quote = await get_philosophical_access_denied_message()
            await message.answer(quote)
            return
    
    try:
        # Инициализируем права по умолчанию, если их еще нет
        await db.initialize_rank_permissions(chat_id)
        
        # Формируем главное меню
        message_text = (
            "⚙️ <b>Настройка прав рангов</b>\n\n"
            "Выберите ранг для настройки:"
        )
        
        # Создаем кнопки для выбора ранга
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        # Кнопки для каждого ранга (кроме пользователя)
        for rank in [1, 2, 3, 4]:
            rank_name = get_rank_name(rank)
            emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
            builder.button(text=f"{emoji} {rank_name}", callback_data=f"rankconfig_select_{rank}")
        
        builder.adjust(2)  # 2 кнопки в ряду
        
        # Кнопка сброса всех прав
        builder.button(text="🔄 Сбросить все к стандарту", callback_data="rankconfig_reset_all")
        
        await message.answer(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек рангов для чата {chat_id}: {e}")
        await message.answer("❌ Ошибка при отображении настроек рангов")


@dp.message(Command("ban"))
@require_admin_rights
async def ban_command(message: Message):
    """Команда бана пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только старшие модераторы и выше
    can_ban = await check_permission(chat_id, user_id, 'can_ban', lambda r: r <= 3)
    if not can_ban:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    time_str = None
    duration_seconds = None
    
    if message.reply_to_message:
        # Формат: /ban [время] (при ответе на сообщение)
        if len(args) == 1:
            # Бан навсегда
            time_str = "навсегда"
            duration_seconds = None
        else:
            # Временный бан - объединяем все аргументы после команды
            time_str = " ".join(args[1:])
            duration_seconds = parse_mute_duration(time_str)
            if duration_seconds is None:
                await message.answer("❌ Некорректный формат времени")
                return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /ban @username [время]
        if len(args) < 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/ban</code> - бан навсегда (при ответе)\n"
                "• <code>/ban 1 час</code> - временный бан (при ответе)\n"
                "• <code>/ban @username</code> - бан навсегда\n"
                "• <code>/ban @username 1 час</code> - временный бан\n\n"
                "Можно указать причину на новой строке:\n"
                "• <code>/ban 1 час\nНарушение правил</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            await message.answer(
                "❌ <b>Пользователь не найден</b>\n\n"
                "Использование:\n"
                "• <code>/ban</code> - бан навсегда (при ответе)\n"
                "• <code>/ban 1 час</code> - временный бан (при ответе)\n"
                "• <code>/ban @username</code> или упоминание - бан навсегда\n"
                "• <code>/ban @username 1 час</code> - временный бан\n\n"
                "Можно указать причину на новой строке:\n"
                "• <code>/ban 1 час\nНарушение правил</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Проверяем, есть ли время
        if len(args) == 2:
            # Бан навсегда
            time_str = "навсегда"
            duration_seconds = None
        else:
            # Временный бан
            time_str = " ".join(args[2:])
            duration_seconds = parse_mute_duration(time_str)
            if duration_seconds is None:
                await message.answer("❌ Некорректный формат времени")
                return
    
    # Проверяем, что пользователь не бот
    if target_user.is_bot:
        await message.answer("❌ Нельзя забанить бота")
        return
    
    # Проверяем, что пользователь не сам себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя забанить самого себя")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя забанить пользователя с равным или более высоким рангом")
        return
    
    try:
        # Вычисляем время окончания бана
        ban_until = None
        if duration_seconds:
            ban_until = datetime.now() + timedelta(seconds=duration_seconds)
        
        # Применяем бан
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            until_date=ban_until
        )
        
        # Записываем наказание в базу данных модерации
        await moderation_db.add_punishment(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            punishment_type="ban",
            reason=reason,
            duration_seconds=duration_seconds,
            expiry_date=ban_until.isoformat() if ban_until else None,
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('ban', duration_seconds)
        await reputation_db.add_recent_punishment(target_user.id, 'ban', duration_seconds)
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение
        if duration_seconds:
            formatted_time = format_mute_duration(duration_seconds)
            message_text = f"🚫 Участник <b>{username_display}</b> был(а) забанен(а) на <i>{formatted_time}</i>\n"
        else:
            message_text = f"🚫 Участник <b>{username_display}</b> был(а) забанен(а) навсегда\n"
        
        if reason:
            message_text += f"📝 <b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "ban", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при бане пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при бане пользователя")


@dp.message(Command("unban"))
@require_admin_rights
async def unban_command(message: Message):
    """Команда разбана пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только старшие модераторы и выше
    can_unban = await check_permission(chat_id, user_id, 'can_unban', lambda r: r <= 3)
    if not can_unban:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /unban (при ответе на сообщение)
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unban</code> (при ответе на сообщение)\n"
                "• <code>/unban @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /unban @username
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unban</code> (при ответе на сообщение)\n"
                "• <code>/unban @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unban</code> (при ответе на сообщение)\n"
                    "• <code>/unban @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем, что пользователь не бот
    if target_user.is_bot:
        await message.answer("❌ Нельзя разбанить бота")
        return
    
    # Проверяем, что пользователь не сам себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя разбанить самого себя")
        return
    
    try:
        # Разбаниваем пользователя
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Деактивируем активные баны в базе данных
        active_bans = await moderation_db.get_active_punishments(chat_id, "ban")
        for ban in active_bans:
            if ban['user_id'] == target_user.id:
                await moderation_db.deactivate_punishment(ban['id'])
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Философские цитаты для разбана
        philosophical_quotes = [
            "🌅 Каждому рассвету предшествует ночь, каждому прощению - ошибка",
            "🌊 Река находит путь к океану, даже если на пути есть камни",
            "🕊️ Птица, которая упала, может снова взлететь",
            "🌱 Из самого темного семени может вырасти самый яркий цветок",
            "🌙 Луна светит даже после самой темной ночи",
            "🍃 Новый лист может вырасти на том же дереве",
            "🌌 Звезды не исчезают навсегда, они просто скрываются за облаками",
            "🌿 Дерево может зацвести заново после зимы",
            "🦋 Гусеница становится бабочкой, преодолевая свои ограничения",
            "🌅 Солнце всегда возвращается, даже после самой долгой ночи"
        ]
        
        import random
        quote = random.choice(philosophical_quotes)
        
        # Сообщение в чат
        message_text = (
            f"✅ <b>{username_display}</b> <i>был(а) разбанен(а)</i>\n"
            f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>\n\n"
            f"<blockquote>{quote}</blockquote>"
        )
        await send_message_with_gif(message, message_text, "unban", parse_mode=ParseMode.HTML)
        
        # Уведомление в ЛС пользователю
        try:
            chat_info = await bot.get_chat(chat_id)
            chat_title = chat_info.title or "Неизвестный чат"
            
            # Создаем кнопку "Открыть чат"
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.button(text="💬 Открыть чат", url=f"https://t.me/{chat_info.username}" if chat_info.username else f"https://t.me/c/{str(chat_id)[4:]}")
            
            await bot.send_message(
                target_user.id,
                f"✅ Вы были разбанены в чате \"{chat_title}\"\n\n"
                f"<blockquote>{quote}</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {target_user.id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при разбане пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при разбане пользователя")


@dp.message(Command("unmute"))
@require_admin_rights
async def unmute_command(message: Message):
    """Команда размута пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_unmute = await check_permission(chat_id, user_id, 'can_unmute', lambda r: r <= 4)
    if not can_unmute:
        if await should_show_hint(chat_id, user_id):
            await message.answer("❌ Недостаточно прав для использования размута")
        return
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Формат: /unmute (при ответе на сообщение)
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unmute</code> (при ответе на сообщение)\n"
                "• <code>/unmute @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /unmute @username
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unmute</code> (при ответе на сообщение)\n"
                "• <code>/unmute @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Извлекаем пользователя из аргументов (поддержка mention и @username)
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unmute</code> (при ответе на сообщение)\n"
                    "• <code>/unmute @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем, что не размучиваем самого себя (хотя это не критично)
    if target_user.id == user_id:
        await message.answer("ℹ️ Вы пытаетесь размутить самого себя")
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:  # Нельзя размутить владельца или администратора (они не могут быть замучены)
        await message.answer("ℹ️ Владелец и администраторы не могут быть замучены")
        return
    
    try:
        # Снимаем мут (восстанавливаем все права)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,  # Оставляем ограниченными права администратора
                can_invite_users=False,
                can_pin_messages=False
            )
        )
        
        # Деактивируем активные наказания типа "mute" для этого пользователя
        try:
            active_punishments = await moderation_db.get_active_punishments(chat_id, "mute")
            for punishment in active_punishments:
                if punishment['user_id'] == target_user.id:
                    await moderation_db.deactivate_punishment(punishment['id'])
                    logger.info(f"Деактивировано наказание {punishment['id']} для пользователя {target_user.id}")
        except Exception as e:
            logger.error(f"Ошибка при деактивации наказаний для пользователя {target_user.id}: {e}")
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Отправляем сообщение в чат о размуте с философией
        try:
            # Философские цитаты для размута
            philosophical_quotes = [
                "🗣️ Голос - это дар, который нужно беречь и использовать мудро",
                "🔄 Второй шанс - это возможность стать лучше",
                "🌅 После тишины приходит время для слов",
                "🕊️ Свобода слова рождает понимание",
                "💬 Каждое слово имеет значение, каждое молчание - тоже",
                "🌟 Освобождение от ограничений открывает новые горизонты",
                "🦋 Как бабочка выходит из кокона, так и слова выходят из молчания",
                "🌊 Река слов снова течет свободно",
                "🎵 После паузы музыка становится еще прекраснее",
                "🌱 Из тишины рождается мудрость",
                "🔓 Ключ к пониманию - это возможность быть услышанным",
                "📖 Новая глава начинается с первого слова",
                "🎭 Каждый актер заслуживает своего выхода на сцену",
                "🌈 После бури всегда наступает затишье",
                "🕯️ Свет разума рассеивает тьму непонимания"
            ]
            
            import random
            quote = random.choice(philosophical_quotes)
            
            logger.info(f"Отправляем сообщение о размуте для пользователя {target_user.id} в чат {chat_id}")
            
            message_text = (
                f"🔊 <b>{username_display}</b> <i>освобожден(а) от тайм-аута</i>\n"
                f"👮 <b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>\n\n"
                f"<blockquote>{quote}</blockquote>"
            )
            await send_message_with_gif(message, message_text, "unmute", parse_mode=ParseMode.HTML)
            
            logger.info(f"Сообщение о размуте отправлено успешно")
            
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение о размуте в чат: {e}")
            # Отправляем простое сообщение если философское не получилось
            try:
                await message.answer(
                    f"🔊 <b>{username_display}</b> размучен",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e2:
                logger.error(f"Не удалось отправить даже простое сообщение о размуте: {e2}")
        
        # Отправляем уведомление пользователю
        try:
            logger.info(f"Отправляем уведомление о размуте пользователю {target_user.id}")
            
            # Создаем кнопку "Открыть чат"
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            
            # Формируем ссылку на чат
            if message.chat.username:
                # Публичный чат
                chat_url = f"https://t.me/{message.chat.username}"
            else:
                # Приватный чат - используем ID
                chat_id_str = str(message.chat.id)
                if chat_id_str.startswith('-100'):
                    # Убираем префикс -100 для супергрупп
                    chat_id_str = chat_id_str[4:]
                chat_url = f"https://t.me/c/{chat_id_str}"
            
            builder.add(InlineKeyboardButton(
                text="💬 Открыть чат",
                url=chat_url
            ))
            
            await bot.send_message(
                target_user.id,
                f"🔊 <b>Вы были размучены</b>\n\n"
                f"В чате <b>{message.chat.title}</b> с вас сняты ограничения на отправку сообщений.",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
            
            logger.info(f"Уведомление о размуте отправлено пользователю {target_user.id} успешно")
            
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {target_user.id}: {e}")
            # Не критично, если не удалось отправить уведомление
        
    except Exception as e:
        logger.error(f"Ошибка при снятии мута пользователю {target_user.id}: {e}")
        await message.answer("❌ Ошибка при снятии мута")


@dp.message(Command("votemute"))
async def votemute_command(message: Message):
    """Команда создания голосования за мут"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем, что это не личные сообщения
    if message.chat.type == 'private':
        await message.answer("Эта команда работает только в группах и супергруппах")
        return
    
    # Проверяем кулдаун создания голосований в чате
    can_create = await votemute_db.check_cooldown(chat_id)
    if not can_create:
        await message.answer("Голосование можно создать раз в 3 минуты. Подождите немного.")
        return
    
    # Проверяем, что нет активного голосования в чате
    active_vote = await votemute_db.get_active_vote(chat_id)
    if active_vote:
        await message.answer("В чате уже есть активное голосование. Дождитесь его завершения.")
        return
    
    # Парсим команду
    args = message.text.split()
    target_user = None
    
    if message.reply_to_message:
        # Формат: /votemute (при ответе на сообщение)
        if len(args) != 1:
            await message.answer(
                "Некорректный формат команды\n\n"
                "Использование:\n"
                "• /votemute (при ответе на сообщение)\n"
                "• /votemute @username"
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        # Формат: /votemute @username
        if len(args) != 2:
            await message.answer(
                "Некорректный формат команды\n\n"
                "Использование:\n"
                "• /votemute (при ответе на сообщение)\n"
                "• /votemute @username"
            )
            return
        
        # Извлекаем username из аргумента
        username = args[1]
        if not username.startswith('@'):
            await message.answer("Укажите username с символом @")
            return
        
        username = username[1:]  # Убираем @
        
        # Ищем пользователя по username в базе данных
        try:
            user_info = await db.get_user_by_username(username)
            if not user_info:
                await message.answer(f"Пользователь @{username} не найден в базе данных. Попросите его написать боту в личные сообщения или использовать команду при ответе на его сообщение.")
                return
            
            # Создаем объект пользователя из данных БД
            from types import SimpleNamespace
            target_user = SimpleNamespace(
                id=user_info['user_id'],
                username=user_info['username'],
                first_name=user_info['first_name'],
                last_name=user_info['last_name'],
                is_bot=user_info['is_bot']
            )
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя @{username}: {e}")
            await message.answer(f"Ошибка при поиске пользователя @{username}")
            return
    
    # Проверяем, что не создаем голосование на самого себя
    if target_user.id == user_id:
        await message.answer("Нельзя создать голосование на самого себя")
        return
    
    # Проверяем, что целевой пользователь не является ботом
    if target_user.is_bot:
        await message.answer("Нельзя создать голосование на бота")
        return
    
    # Проверяем ранг целевого пользователя (только обычные участники)
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank != RANK_USER:
        await message.answer("Голосование можно создать только на обычных участников")
        return
    
    # Создаем голосование с стандартными настройками
    try:
        # Устанавливаем кулдаун
        await votemute_db.set_cooldown(chat_id)
        
        # Создаем голосование в БД
        vote_id = await votemute_db.create_vote(
            chat_id=chat_id,
            target_user_id=target_user.id,
            creator_id=user_id,
            mute_duration=30 * 60,  # 30 минут в секундах
            required_votes=5,       # 5 голосов для завершения
            vote_duration=5,        # 5 минут голосования
            is_pinned=False,        # Без закрепа
            target_username=target_user.username,
            target_first_name=target_user.first_name,
            target_last_name=target_user.last_name,
            creator_username=message.from_user.username,
            creator_first_name=message.from_user.first_name,
            creator_last_name=message.from_user.last_name
        )
        
        # Отправляем сообщение с голосованием
        vote_data = {
            'target_user_id': target_user.id,
            'target_username': target_user.username,
            'target_first_name': target_user.first_name,
            'target_last_name': target_user.last_name,
            'creator_id': user_id,
            'creator_username': message.from_user.username,
            'creator_first_name': message.from_user.first_name,
            'creator_last_name': message.from_user.last_name,
            'mute_duration': 30 * 60,
            'required_votes': 5,
            'vote_duration': 5,
            'vote_id': vote_id
        }
        
        vote_message = await send_votemute_message(chat_id, vote_id, vote_data)
        
        # Обновляем message_id в БД
        await votemute_db.update_vote_message_id(vote_id, vote_message.message_id)
        
        # Запускаем таймер
        asyncio.create_task(votemute_timer(vote_id, 5 * 60))  # 5 минут
        
    except Exception as e:
        logger.error(f"Ошибка при создании голосования: {e}")
        await message.answer("❌ Ошибка при создании голосования")


async def show_votemute_config_panel(message: Message, state: FSMContext):
    """Показать панель конфигурации голосования"""
    data = await state.get_data()
    
    # Формируем имя целевого пользователя
    target_name = data['target_first_name'] or f"@{data['target_username']}" if data['target_username'] else f"ID{data['target_user_id']}"
    
    # Создаем клавиатуру главного меню
    builder = InlineKeyboardBuilder()
    
    # Кнопки выбора категорий (2 столбца)
    mute_duration_text = f"{data['mute_duration']} мин" if data['mute_duration'] < 60 else f"{data['mute_duration'] // 60} час"
    
    builder.add(InlineKeyboardButton(
        text=f"⏱️ Время мута: {mute_duration_text}",
        callback_data="votemute_menu_duration"
    ))
    builder.add(InlineKeyboardButton(
        text=f"📊 Голосов: {data['required_votes']}",
        callback_data="votemute_menu_votes"
    ))
    builder.add(InlineKeyboardButton(
        text=f"⏰ Время голосования: {data['vote_duration']} мин",
        callback_data="votemute_menu_time"
    ))
    builder.add(InlineKeyboardButton(
        text=f"📌 Закреп: {'Да' if data['pin_message'] else 'Нет'}",
        callback_data="votemute_menu_pin"
    ))
    
    builder.adjust(2)  # 2 столбца
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(
        text="⚡ Быстрое создание",
        callback_data="votemute_quick"
    ))
    builder.add(InlineKeyboardButton(
        text="🚀 Создать голосование",
        callback_data="votemute_start"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отменить",
        callback_data="votemute_cancel"
    ))
    
    builder.adjust(1)
    
    # Формируем текст сообщения
    mute_duration_text = f"{data['mute_duration']} мин" if data['mute_duration'] < 60 else f"{data['mute_duration'] // 60} час"
    
    text = f"""<b>⚙️ Настройка голосования за мут</b>

<i>👤 Нарушитель:</i> {target_name}
<i>⏱️ Время мута:</i> {mute_duration_text}
<i>📊 Голосов для завершения:</i> {data['required_votes']}
<i>⏰ Голосование длится:</i> {data['vote_duration']} мин
<i>📌 Закрепить сообщение:</i> {'Да' if data['pin_message'] else 'Нет'}

Выберите параметры:"""
    
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def show_votemute_config_panel_edit(callback: types.CallbackQuery, state: FSMContext):
    """Обновить панель конфигурации голосования"""
    data = await state.get_data()
    
    # Формируем имя целевого пользователя
    target_name = data['target_first_name'] or f"@{data['target_username']}" if data['target_username'] else f"ID{data['target_user_id']}"
    
    # Создаем клавиатуру главного меню
    builder = InlineKeyboardBuilder()
    
    # Кнопки выбора категорий (2 столбца)
    mute_duration_text = f"{data['mute_duration']} мин" if data['mute_duration'] < 60 else f"{data['mute_duration'] // 60} час"
    
    builder.add(InlineKeyboardButton(
        text=f"⏱️ Время мута: {mute_duration_text}",
        callback_data="votemute_menu_duration"
    ))
    builder.add(InlineKeyboardButton(
        text=f"📊 Голосов: {data['required_votes']}",
        callback_data="votemute_menu_votes"
    ))
    builder.add(InlineKeyboardButton(
        text=f"⏰ Время голосования: {data['vote_duration']} мин",
        callback_data="votemute_menu_time"
    ))
    builder.add(InlineKeyboardButton(
        text=f"📌 Закреп: {'Да' if data['pin_message'] else 'Нет'}",
        callback_data="votemute_menu_pin"
    ))
    
    builder.adjust(2)  # 2 столбца
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(
        text="⚡ Быстрое создание",
        callback_data="votemute_quick"
    ))
    builder.add(InlineKeyboardButton(
        text="🚀 Создать голосование",
        callback_data="votemute_start"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отменить",
        callback_data="votemute_cancel"
    ))
    
    builder.adjust(1)
    
    # Формируем текст сообщения
    mute_duration_text = f"{data['mute_duration']} мин" if data['mute_duration'] < 60 else f"{data['mute_duration'] // 60} час"
    
    text = f"""<b>⚙️ Настройка голосования за мут</b>

<i>👤 Нарушитель:</i> {target_name}
<i>⏱️ Время мута:</i> {mute_duration_text}
<i>📊 Голосов для завершения:</i> {data['required_votes']}
<i>⏰ Голосование длится:</i> {data['vote_duration']} мин
<i>📌 Закрепить сообщение:</i> {'Да' if data['pin_message'] else 'Нет'}

Выберите параметры:"""
    
    await fast_edit_message(callback, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def show_duration_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показать меню выбора времени мута"""
    data = await state.get_data()
    
    builder = InlineKeyboardBuilder()
    
    # Время мута (2 столбца)
    mute_durations = [
        (5, "5 мин"), (15, "15 мин"), (30, "30 мин"), (60, "1 час"),
        (180, "3 часа"), (360, "6 часов"), (720, "12 часов")
    ]
    
    for duration, label in mute_durations:
        selected = "✅" if data['mute_duration'] == duration else ""
        builder.add(InlineKeyboardButton(
            text=f"{selected} {label}",
            callback_data=f"votemute_duration_{duration}"
        ))
    
    builder.adjust(2)  # 2 столбца
    
    # Кнопка назад
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="votemute_back"
    ))
    
    builder.adjust(1)
    
    text = "<b>⏱️ Выберите время мута</b>"
    
    await fast_edit_message(callback, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def show_votes_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показать меню выбора количества голосов"""
    data = await state.get_data()
    
    builder = InlineKeyboardBuilder()
    
    # Количество голосов (2 столбца)
    for votes in range(3, 10):
        selected = "✅" if data['required_votes'] == votes else ""
        builder.add(InlineKeyboardButton(
            text=f"{selected} {votes}",
            callback_data=f"votemute_reqvotes_{votes}"
        ))
    
    builder.adjust(2)  # 2 столбца
    
    # Кнопка назад
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="votemute_back"
    ))
    
    builder.adjust(1)
    
    text = "<b>📊 Выберите количество голосов для завершения</b>"
    
    await fast_edit_message(callback, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def show_time_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показать меню выбора времени голосования"""
    data = await state.get_data()
    
    builder = InlineKeyboardBuilder()
    
    # Время голосования (2 столбца)
    vote_times = [(3, "3 мин"), (5, "5 мин"), (7, "7 мин"), (10, "10 мин")]
    
    for time, label in vote_times:
        selected = "✅" if data['vote_duration'] == time else ""
        builder.add(InlineKeyboardButton(
            text=f"{selected} {label}",
            callback_data=f"votemute_votetime_{time}"
        ))
    
    builder.adjust(2)  # 2 столбца
    
    # Кнопка назад
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="votemute_back"
    ))
    
    builder.adjust(1)
    
    text = "<b>⏰ Выберите время голосования</b>"
    
    await fast_edit_message(callback, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def show_pin_menu(callback: types.CallbackQuery, state: FSMContext):
    """Показать меню выбора закрепа"""
    data = await state.get_data()
    
    builder = InlineKeyboardBuilder()
    
    # Закреп сообщения
    pin_text = "✅ Закрепить" if data['pin_message'] else "Закрепить"
    builder.add(InlineKeyboardButton(
        text=pin_text,
        callback_data=f"votemute_pin_{not data['pin_message']}"
    ))
    
    no_pin_text = "✅ Не закреплять" if not data['pin_message'] else "Не закреплять"
    builder.add(InlineKeyboardButton(
        text=no_pin_text,
        callback_data=f"votemute_pin_{not data['pin_message']}"
    ))
    
    builder.adjust(1)
    
    # Кнопка назад
    builder.add(InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="votemute_back"
    ))
    
    builder.adjust(1)
    
    text = "<b>📌 Выберите закреп сообщения</b>"
    
    await fast_edit_message(callback, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@dp.message(Command("cleanup"))
@require_admin_rights
async def cleanup_command(message: Message):
    """Команда принудительной очистки дубликатов"""
    try:
        await message.answer("🔄 Начинаю очистку дубликатов...")
        
        # Очищаем дубликаты
        result = await db.cleanup_duplicate_chats()
        
        if result:
            await message.answer("✅ Дубликаты успешно очищены!")
        else:
            await message.answer("❌ Ошибка при очистке дубликатов")
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды cleanup: {e}")
        await message.answer("❌ Произошла ошибка при очистке")


@dp.message(Command("net"))
async def net_command(message: Message):
    """Команда управления сеткой чатов"""
    if message.chat.type != 'private':
        await message.answer("❌ Команда /net доступна только в личных сообщениях с ботом!")
        return
    
    try:
        user_id = message.from_user.id
        
        # Получаем сети пользователя
        networks = await network_db.get_user_networks(user_id)
        
        text = """🌐 <b>Сетка чатов PIXEL</b>

<blockquote>Сетка чатов позволяет связать до <b>5 чатов</b> для:
📊 Просмотра общей статистики по всем чатам

⚙️ Синхронизации настроек модерации между чатами  

🎛️ Централизованного управления чатами
</blockquote>

<blockquote><code>ℹ️ Важно: Вы должны быть владельцем всех чатов в сети!</code>
</blockquote>

<blockquote><code>🔄 Если что-то пойдет не так, используйте:</code>
<code>/chatnet update</code> - обновить информацию о чатах
</blockquote>"""
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка создания новой сетки (только если нет существующих сеток)
        if not networks:
            builder.add(InlineKeyboardButton(
                text="🔗 Связать чаты",
                callback_data="net_create"
            ))
        
        # Кнопка просмотра существующих сетей
        if networks:
            builder.add(InlineKeyboardButton(
                text=f"📋 Моя сетка",
                callback_data="net_list"
            ))
        
        builder.adjust(1)
        
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /net: {e}")
        await message.answer("❌ Произошла ошибка при отображении панели сетки чатов")


@dp.message(Command("netconnect"))
async def netconnect_command(message: Message):
    """Команда подключения к сетке чатов"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /netconnect должна использоваться в чате, который нужно добавить в сетку!")
        return
    
    try:
        # Парсим код из команды
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /netconnect <код>\nПример: /netconnect 1234")
            return
        
        code = command_parts[1].strip()
        if not code.isdigit() or len(code) != 4:
            await message.answer("❌ Код должен быть 4-значным числом!\nПример: /netconnect 1234")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # Проверяем, что пользователь - владелец чата
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await message.answer("❌ Только владелец чата может добавлять его в сетку!")
            return
        
        # Проверяем, не находится ли чат уже в сети
        if await network_db.is_chat_in_network(chat_id):
            await message.answer("❌ Этот чат уже находится в сетке чатов!")
            return
        
        # Проверяем код
        code_info = await network_db.validate_code(code)
        if not code_info:
            await message.answer("❌ Неверный или истекший код!")
            return
        
        network_id = code_info['network_id']
        code_type = code_info['code_type']
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await message.answer("❌ Вы не можете использовать этот код! Только владелец сети может добавлять чаты.")
            return
        
        # Проверяем лимит чатов в сети
        chat_count = await network_db.get_network_chat_count(network_id)
        if chat_count >= 5:
            await message.answer("❌ В сетке уже максимальное количество чатов (5)!")
            return
        
        # Добавляем чат в сеть
        is_primary = (code_type == 'create' and len(await network_db.get_network_chats(network_id)) == 0)
        success = await network_db.add_chat_to_network(network_id, chat_id, is_primary)
        if not success:
            await message.answer("❌ Ошибка при добавлении чата в сетку!")
            return
        
        # Получаем информацию о сети
        network_chats = await network_db.get_network_chats(network_id)
        
        if code_type == 'create' and len(network_chats) == 1:
            # Первый чат в новой сети
            await message.answer(f"""✅ <b>Чат добавлен в новую сетку!</b>

🌐 Сетка создана успешно
📊 Количество чатов: 1/5

Теперь добавьте второй чат, используя тот же код в другом чате:
<code>/netconnect {code}</code>

Код действует 10 минут.""", parse_mode=ParseMode.HTML)
        elif code_type == 'create' and len(network_chats) == 2:
            # Второй чат в новой сети - помечаем код как использованный
            await network_db.mark_code_as_used(code)
            await message.answer(f"""✅ <b>Сетка создана!</b>

🌐 Сетка #{network_id} готова к использованию
📊 Количество чатов: {len(network_chats)}/5

Используйте /mychats для управления сеткой.""", parse_mode=ParseMode.HTML)
        else:
            # Дополнительный чат в существующей сети
            await message.answer(f"""✅ <b>Чат добавлен в сетку!</b>

🌐 Сетка обновлена
📊 Количество чатов: {len(network_chats)}/5

Сетка готова к использованию!""", parse_mode=ParseMode.HTML)
        
        # Отправляем уведомление владельцу в ЛС
        try:
            await bot.send_message(
                user_id,
                f"""🌐 <b>Обновление сетки чатов</b>

Чат "{message.chat.title}" добавлен в сетку #{network_id}

📊 Всего чатов в сетке: {len(network_chats)}/5

Используйте /mychats для управления сеткой.""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления владельцу: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /netconnect: {e}")
        await message.answer("❌ Произошла ошибка при подключении к сетке!")


@dp.message(Command("netadd"))
async def netadd_command(message: Message):
    """Команда добавления чата в существующую сетку"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /netadd должна использоваться в чате, который нужно добавить в сетку!")
        return
    
    try:
        # Парсим код из команды
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /netadd <код>\nПример: /netadd 42")
            return
        
        code = command_parts[1].strip()
        if not code.isdigit() or len(code) != 2:
            await message.answer("❌ Код должен быть 2-значным числом!\nПример: /netadd 42")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # Проверяем, что пользователь - владелец чата
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await message.answer("❌ Только владелец чата может добавлять его в сетку!")
            return
        
        # Проверяем, не находится ли чат уже в сети
        if await network_db.is_chat_in_network(chat_id):
            await message.answer("❌ Этот чат уже находится в сетке чатов!")
            return
        
        # Проверяем код
        code_info = await network_db.validate_code(code)
        if not code_info:
            await message.answer("❌ Неверный или истекший код!")
            return
        
        network_id = code_info['network_id']
        code_type = code_info['code_type']
        
        # Проверяем, что это код для добавления
        if code_type != 'add':
            await message.answer("❌ Этот код предназначен для создания новой сетки, а не для добавления чата!")
            return
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await message.answer("❌ Вы не можете использовать этот код! Только владелец сети может добавлять чаты.")
            return
        
        # Проверяем лимит чатов в сети
        chat_count = await network_db.get_network_chat_count(network_id)
        if chat_count >= 5:
            await message.answer("❌ В сетке уже максимальное количество чатов (5)!")
            return
        
        # Добавляем чат в сеть
        success = await network_db.add_chat_to_network(network_id, chat_id)
        if not success:
            await message.answer("❌ Ошибка при добавлении чата в сетку!")
            return
        
        # Помечаем код как использованный (коды типа 'add' одноразовые)
        await network_db.mark_code_as_used(code)
        
        # Получаем информацию о сети
        network_chats = await network_db.get_network_chats(network_id)
        
        await message.answer(f"""✅ <b>Чат добавлен в сетку!</b>

🌐 Сетка обновлена
📊 Количество чатов: {len(network_chats)}/5

Сетка готова к использованию!""", parse_mode=ParseMode.HTML)
        
        # Отправляем уведомление владельцу в ЛС
        try:
            await bot.send_message(
                user_id,
                f"""🌐 <b>Обновление сетки чатов</b>

Чат "{message.chat.title}" добавлен в сетку #{network_id}

📊 Всего чатов в сетке: {len(network_chats)}/5

Используйте /mychats для управления сеткой.""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления владельцу: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /netadd: {e}")
        await message.answer("❌ Произошла ошибка при добавлении в сетку!")


@dp.message(Command("chatnet"))
async def chatnet_command(message: Message):
    """Команда просмотра информации о сетке текущего чата"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /chatnet работает только в чатах!")
        return
    
    # Проверяем, есть ли параметр обновления
    command_parts = message.text.split()
    force_update = len(command_parts) > 1 and command_parts[1].lower() in ['update', 'refresh', 'обновить']
    
    try:
        chat_id = message.chat.id
        
        # Проверяем, находится ли чат в сети
        network_info = await network_db.get_network_by_chat(chat_id)
        if not network_info:
            await message.answer("❌ Этот чат не находится в сетке чатов!")
            return
        
        network_id = network_info['network_id']
        owner_id = network_info['owner_id']
        
        # Если запрашивается обновление, проверяем права и кулдаун
        if force_update:
            user_id = message.from_user.id
            
            # Проверяем, что пользователь - владелец сетки
            if user_id != owner_id:
                await message.answer("❌ Только владелец сетки может обновлять информацию о чатах!")
                return
            
            # Проверяем кулдаун
            can_update, remaining_time = check_chatnet_update_cooldown(user_id)
            if not can_update:
                minutes = remaining_time // 60
                seconds = remaining_time % 60
                if minutes > 0:
                    time_str = f"{minutes}м {seconds}с"
                else:
                    time_str = f"{seconds}с"
                await message.answer(f"⏰ Обновление доступно через {time_str}")
                return
        
        # Получаем все чаты в сети (сортированные по приоритету)
        network_chats = await network_db.get_network_chats_sorted(network_id, 'priority')
        
        # Получаем информацию о чатах
        chat_info_list = []
        total_messages_today = 0
        total_messages_week = 0
        total_members = 0
        active_users_today = set()
        
        for chat_data in network_chats:
            chat_id_in_network = chat_data['chat_id']
            
            # Получаем информацию о чате
            chat_info = await db.get_chat(chat_id_in_network)
            if not chat_info:
                continue
            
            # Обновляем информацию о чате только при принудительном обновлении
            if force_update:
                try:
                    chat_obj = await bot.get_chat(chat_id_in_network)
                    # Обновляем название и статус публичности в базе данных
                    await db.update_chat_info(
                        chat_id_in_network, 
                        title=chat_obj.title, 
                        is_public=bool(hasattr(chat_obj, 'username') and chat_obj.username)
                    )
                except Exception as e:
                    logger.warning(f"Не удалось обновить информацию о чате {chat_id_in_network}: {e}")
            
            # Получаем статистику за сегодня
            messages_today = await db.get_today_message_count(chat_id_in_network)
            total_messages_today += messages_today
            
            # Получаем статистику за неделю
            week_stats = await db.get_daily_stats(chat_id_in_network, 7)
            messages_week = sum(stat['message_count'] for stat in week_stats)
            total_messages_week += messages_week
            
            # Получаем активных пользователей за сегодня
            top_users = await db.get_top_users_today(chat_id_in_network, 100)
            for user in top_users:
                active_users_today.add(user['user_id'])
            
            # Получаем количество участников
            try:
                chat_member_count = await bot.get_chat_member_count(chat_id_in_network)
                total_members += chat_member_count
            except:
                chat_member_count = "?"
            
            chat_info_list.append({
                'title': chat_info['chat_title'],
                'chat_id': chat_id_in_network,
                'messages_today': messages_today,
                'messages_week': messages_week,
                'member_count': chat_member_count,
                'is_primary': chat_data['is_primary']
            })
        
        # Формируем текст
        update_info = " 🔄" if force_update else ""
        text = f"""🌐 <b>Сетка чатов #{network_id}</b>{update_info}

📊 <b>Общая статистика:</b>
• Сообщений сегодня: {total_messages_today}
• Сообщений за неделю: {total_messages_week}
• Активных пользователей сегодня: {len(active_users_today)}
• Всего участников: {total_members if total_members > 0 else '?'}

📋 <b>Чаты в сетке ({len(chat_info_list)}/5):</b>"""
        
        for i, chat_info in enumerate(chat_info_list, 1):
            # Проверяем, является ли чат публичным
            try:
                chat_obj = await bot.get_chat(chat_info['chat_id'])
                if hasattr(chat_obj, 'username') and chat_obj.username:
                    # Публичный чат - делаем название кликабельным
                    chat_link = f"https://t.me/{chat_obj.username}"
                    chat_title = f'<a href="{chat_link}">{chat_info["title"]}</a>'
                else:
                    # Приватный чат - обычное название
                    chat_title = f"<b>{chat_info['title']}</b>"
            except Exception as e:
                # Чат недоступен - показываем с пометкой
                chat_title = f"<b>{chat_info['title']}</b> ❌"
                logger.warning(f"Чат {chat_info['chat_id']} ({chat_info['title']}) недоступен: {e}")
            
            text += f"\n\n{i}. {chat_title}"
            text += f"\n   📊 Сегодня: {chat_info['messages_today']} сообщений"
            text += f"\n   📈 За неделю: {chat_info['messages_week']} сообщений"
            text += f"\n   👥 Участников: {chat_info['member_count']}"
        
        
        await message.answer(text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /chatnet: {e}")
        await message.answer("❌ Произошла ошибка при получении информации о сетке!")


@dp.message(Command("refreshchat"))
async def refresh_chat_command(message: Message):
    """Команда для обновления информации о чате"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /refreshchat работает только в чатах!")
        return
    
    try:
        chat_id = message.chat.id
        
        # Получаем актуальную информацию о чате
        chat_obj = await bot.get_chat(chat_id)
        
        # Обновляем информацию в базе данных
        await db.update_chat_info(chat_id, title=chat_obj.title, is_public=bool(hasattr(chat_obj, 'username') and chat_obj.username))
        
        await message.answer(f"""✅ <b>Информация о чате обновлена!</b>

📝 <b>Название:</b> {chat_obj.title}
🔗 <b>Username:</b> {chat_obj.username if hasattr(chat_obj, 'username') and chat_obj.username else 'Не установлен'}
🆔 <b>ID:</b> <code>{chat_id}</code>""", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /refreshchat: {e}")
        await message.answer("❌ Произошла ошибка при обновлении информации о чате!")


@dp.message(Command("unnet"))
async def unnet_command(message: Message):
    """Команда удаления чата из сетки"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /unnet должна использоваться в чате, который нужно удалить из сетки!")
        return
    
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # Проверяем, что пользователь - владелец чата
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await message.answer("❌ Только владелец чата может удалять его из сетки!")
            return
        
        # Проверяем, находится ли чат в сети
        network_info = await network_db.get_network_by_chat(chat_id)
        if not network_info:
            await message.answer("❌ Этот чат не находится в сетке чатов!")
            return
        
        network_id = network_info['network_id']
        
        # Получаем количество чатов в сети
        chat_count = await network_db.get_network_chat_count(network_id)
        
        if chat_count <= 1:
            await message.answer("❌ Нельзя удалить последний чат из сетки! Сначала добавьте другие чаты.")
            return
        
        # Создаем кнопку подтверждения
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"unnet_confirm_{chat_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="unnet_cancel"
        ))
        builder.adjust(1)
        
        await message.answer(
            f"""⚠️ <b>Подтверждение удаления</b>

Вы действительно хотите удалить чат "{message.chat.title}" из сетки #{network_id}?

После удаления в сетке останется {chat_count - 1} чат(ов).""",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка в команде /unnet: {e}")
        await message.answer("❌ Произошла ошибка при попытке удаления из сетки!")


# ========== CALLBACK ОБРАБОТЧИКИ ДЛЯ СЕТКИ ЧАТОВ ==========

@dp.callback_query(F.data == "net_create")
async def net_create_callback(callback: types.CallbackQuery):
    """Обработчик создания новой сетки"""
    try:
        user_id = callback.from_user.id
        
        # Проверяем, есть ли уже сетка у пользователя
        existing_networks = await network_db.get_user_networks(user_id)
        if existing_networks:
            await callback.message.edit_text("❌ У вас уже есть сетка чатов! Один пользователь может иметь только одну сетку.\n\nИспользуйте /net для управления существующей сеткой.")
            return
        
        # Создаем новую сеть
        network_id = await network_db.create_network(user_id)
        if not network_id:
            await callback.message.edit_text("❌ Ошибка при создании сетки!")
            return
        
        # Генерируем код для связывания
        code = await network_db.generate_code(network_id, 'create')
        if not code:
            await callback.message.edit_text("❌ Ошибка при генерации кода! Попробуйте позже.")
            return
        
        text = f"""🔗 <b>Создание сетки чатов</b>

✅ Сетка #{network_id} создана успешно!

📝 <b>Инструкция:</b>
1. Скопируйте код: <code>{code}</code>
2. Перейдите в первый чат и выполните:
   <code>/netconnect {code}</code>
3. Перейдите во второй чат и выполните:
   <code>/netconnect {code}</code>

⏰ Код действует 10 минут

После добавления двух чатов сетка будет готова к использованию!"""
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="📋 Мои сетки",
            callback_data="net_list"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_back"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_create_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data == "net_list")
async def net_list_callback(callback: types.CallbackQuery):
    """Обработчик просмотра списка сеток"""
    try:
        user_id = callback.from_user.id
        
        # Получаем все сети пользователя
        networks = await network_db.get_user_networks(user_id)
        if not networks:
            await callback.message.edit_text("❌ У вас нет сеток чатов!")
            return
        
        # Берем первую (и единственную) сетку
        network = networks[0]
        network_id = network['network_id']
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🎛️ <b>Управление чатами</b>\n\n🌐 <b>Сетка #{network_id}</b> ({len(network_chats)}/5 чатов)\n\n"
        
        # Собираем информацию о чатах
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                # Проверяем доступность чата и обновляем информацию
                chat_accessible = True
                try:
                    chat_obj = await bot.get_chat(chat_id)
                    # Обновляем информацию о чате в базе данных
                    await db.update_chat_info(
                        chat_id, 
                        title=chat_obj.title, 
                        is_public=bool(hasattr(chat_obj, 'username') and chat_obj.username)
                    )
                except Exception as e:
                    chat_accessible = False
                    logger.warning(f"Чат {chat_id} ({chat_info['chat_title']}) недоступен в net_list: {e}")
                
                # Получаем статистику
                messages_today = await db.get_today_message_count(chat_id)
                week_stats = await db.get_daily_stats(chat_id, 7)
                messages_week = sum(stat['message_count'] for stat in week_stats)
                
                # Получаем количество участников
                try:
                    member_count = await bot.get_chat_member_count(chat_id)
                except:
                    member_count = "?"
                
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                status_mark = " ❌" if not chat_accessible else ""
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}{status_mark}\n"
                text += f"   📊 Сегодня: {messages_today} | За неделю: {messages_week}\n"
                text += f"   👥 Участников: {member_count}\n\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка управления сеткой
        builder.add(InlineKeyboardButton(
            text=f"🌐 Управление сеткой #{network_id}",
            callback_data=f"net_view_{network_id}"
        ))
        
        # Кнопка удаления чатов (только если больше одного чата)
        if len(network_chats) > 1:
            builder.add(InlineKeyboardButton(
                text="🗑️ Удалить чат из сетки",
                callback_data=f"remove_chat_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_back"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_list_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_view_"))
async def net_view_callback(callback: types.CallbackQuery):
    """Обработчик просмотра конкретной сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🌐 <b>Управление сеткой #{network_id}</b>\n\n"
        text += f"📊 Чатов в сетке: {len(network_chats)}/5\n\n"
        
        # Информация о чатах
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки управления
        if len(network_chats) < 5:
            builder.add(InlineKeyboardButton(
                text="➕ Добавить чат",
                callback_data=f"net_code_gen_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="⚙️ Синхронизировать настройки",
            callback_data=f"net_sync_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="📊 Статистика",
            callback_data=f"net_stats_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🎯 Управление приоритетами",
            callback_data=f"net_priority_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🛡️ Управление модерацией",
            callback_data=f"net_moderation_{network_id}"
        ))
        
        # Кнопка удаления чатов (только если больше одного чата)
        if len(network_chats) > 1:
            builder.add(InlineKeyboardButton(
                text="🗑️ Удалить чат из сетки",
                callback_data=f"remove_chat_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🗑️ Удалить сетку",
            callback_data=f"net_delete_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_list"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_view_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_code_gen_"))
async def net_code_gen_callback(callback: types.CallbackQuery):
    """Обработчик генерации кода для добавления чата"""
    try:
        network_id = int(callback.data.split("_")[3])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Проверяем лимит чатов
        chat_count = await network_db.get_network_chat_count(network_id)
        if chat_count >= 5:
            await callback.answer("❌ В сетке уже максимальное количество чатов!")
            return
        
        # Генерируем код
        code = await network_db.generate_code(network_id, 'add')
        if not code:
            await callback.answer("❌ Ошибка при генерации кода! Попробуйте позже.")
            return
        
        text = f"""➕ <b>Добавление чата в сетку #{network_id}</b>

📝 <b>Инструкция:</b>
1. Скопируйте код: <code>{code}</code>
2. Перейдите в чат, который нужно добавить
3. Выполните команду: <code>/netadd {code}</code>

⏰ Код действует 10 минут и одноразовый"""
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_code_gen_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("unnet_confirm_"))
async def unnet_confirm_callback(callback: types.CallbackQuery):
    """Обработчик подтверждения удаления чата из сетки"""
    try:
        chat_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец чата
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await callback.answer("❌ У вас нет прав для удаления этого чата!")
            return
        
        # Получаем информацию о сети
        network_info = await network_db.get_network_by_chat(chat_id)
        if not network_info:
            await callback.answer("❌ Чат не находится в сетке!")
            return
        
        network_id = network_info['network_id']
        
        # Удаляем чат из сети
        success = await network_db.remove_chat_from_network(chat_id)
        if not success:
            await callback.answer("❌ Ошибка при удалении чата из сетки!")
            return
        
        # Проверяем, остались ли чаты в сети
        remaining_chats = await network_db.get_network_chat_count(network_id)
        
        if remaining_chats == 0:
            # Удаляем пустую сеть
            await network_db.delete_network(network_id)
            await callback.message.edit_text("✅ Чат удален из сетки. Сетка была удалена, так как в ней не осталось чатов.")
        else:
            await callback.message.edit_text(f"✅ Чат удален из сетки #{network_id}. В сетке осталось {remaining_chats} чат(ов).")
        
    except Exception as e:
        logger.error(f"Ошибка в unnet_confirm_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data == "unnet_cancel")
async def unnet_cancel_callback(callback: types.CallbackQuery):
    """Обработчик отмены удаления чата из сетки"""
    await callback.message.edit_text("❌ Удаление отменено.")
    await callback.answer()


@dp.callback_query(F.data == "net_back")
async def net_back_callback(callback: types.CallbackQuery):
    """Обработчик возврата в главное меню сетки"""
    try:
        user_id = callback.from_user.id
        
        # Получаем сети пользователя
        networks = await network_db.get_user_networks(user_id)
        
        text = """🌐 <b>Сетка чатов PIXEL</b>

<blockquote>Сетка чатов позволяет связать до <b>5 чатов</b> для:
📊 Просмотра общей статистики по всем чатам

⚙️ Синхронизации настроек модерации между чатами

🎛️ Централизованного управления чатами
</blockquote>

<blockquote>⚠️ <b>Важно:</b> Вы должны быть владельцем всех чатов в сети!
</blockquote>"""
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка создания новой сетки (только если нет существующих сеток)
        if not networks:
            builder.add(InlineKeyboardButton(
                text="🔗 Связать чаты",
                callback_data="net_create"
            ))
        
        # Кнопка просмотра существующих сетей
        if networks:
            builder.add(InlineKeyboardButton(
                text=f"📋 Моя сетка",
                callback_data="net_list"
            ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_back_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_priority_"))
async def net_priority_callback(callback: types.CallbackQuery):
    """Обработчик управления приоритетами чатов в сетке"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети (сортированные по приоритету)
        network_chats = await network_db.get_network_chats_sorted(network_id, 'priority')
        
        text = f"🎯 <b>Управление приоритетами сетки #{network_id}</b>\n\n"
        text += "<b>Текущий порядок чатов:</b>\n"
        text += "• Больший приоритет = выше в списке\n"
        text += "• Приоритет 0 = обычный порядок\n\n"
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                priority = chat_data['priority']
                priority_text = f"Приоритет: {priority}" if priority > 0 else "Обычный"
                text += f"{i}. <b>{chat_info['chat_title']}</b>\n   {priority_text}\n\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки для каждого чата
        for chat_data in network_chats:
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                builder.add(InlineKeyboardButton(
                    text=f"📝 {chat_info['chat_title'][:20]}...",
                    callback_data=f"priority_chat_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔄 Авто-сортировка по активности",
            callback_data=f"priority_auto_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_priority_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("priority_chat_"))
async def priority_chat_callback(callback: types.CallbackQuery):
    """Обработчик выбора чата для изменения приоритета"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем информацию о чате
        chat_info = await db.get_chat(chat_id)
        if not chat_info:
            await callback.answer("❌ Чат не найден!")
            return
        
        # Получаем текущий приоритет
        network_chats = await network_db.get_network_chats_sorted(network_id, 'priority')
        current_priority = 0
        for chat_data in network_chats:
            if chat_data['chat_id'] == chat_id:
                current_priority = chat_data['priority']
                break
        
        text = f"📝 <b>Изменение приоритета чата</b>\n\n"
        text += f"<b>Чат:</b> {chat_info['chat_title']}\n"
        text += f"<b>Текущий приоритет:</b> {current_priority}\n\n"
        text += "<b>Выберите новый приоритет:</b>\n"
        text += "• 0 = Обычный порядок\n"
        text += "• 1-10 = Высокий приоритет\n"
        text += "• Чем больше число, тем выше в списке"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки приоритетов
        for priority in [0, 1, 3, 5, 10]:
            if priority == current_priority:
                text_btn = f"✅ {priority}"
            else:
                text_btn = f"{priority}"
            
            builder.add(InlineKeyboardButton(
                text=text_btn,
                callback_data=f"set_priority_{network_id}_{chat_id}_{priority}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_priority_{network_id}"
        ))
        
        builder.adjust(3, 1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в priority_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("set_priority_"))
async def set_priority_callback(callback: types.CallbackQuery):
    """Обработчик установки приоритета чата"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        chat_id = int(parts[3])
        priority = int(parts[4])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Устанавливаем приоритет
        success = await network_db.set_chat_priority(network_id, chat_id, priority)
        if success:
            await callback.answer(f"✅ Приоритет установлен: {priority}")
            # Возвращаемся к управлению приоритетами
            await net_priority_callback(callback)
        else:
            await callback.answer("❌ Ошибка при установке приоритета!")
        
    except Exception as e:
        logger.error(f"Ошибка в set_priority_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("priority_auto_"))
async def priority_auto_callback(callback: types.CallbackQuery):
    """Обработчик автоматической сортировки по активности"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        # Собираем статистику активности для каждого чата
        chat_activity = []
        for chat_data in network_chats:
            chat_id = chat_data['chat_id']
            
            # Получаем статистику за неделю
            week_stats = await db.get_daily_stats(chat_id, 7)
            total_messages = sum(stat['message_count'] for stat in week_stats)
            
            chat_activity.append({
                'chat_id': chat_id,
                'messages': total_messages
            })
        
        # Сортируем по активности (больше сообщений = выше приоритет)
        chat_activity.sort(key=lambda x: x['messages'], reverse=True)
        
        # Устанавливаем приоритеты
        for i, chat_info in enumerate(chat_activity):
            priority = len(chat_activity) - i  # 5, 4, 3, 2, 1
            await network_db.set_chat_priority(network_id, chat_info['chat_id'], priority)
        
        await callback.answer("✅ Авто-сортировка по активности завершена!")
        # Возвращаемся к управлению приоритетами
        await net_priority_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в priority_auto_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_moderation_"))
async def net_moderation_callback(callback: types.CallbackQuery):
    """Обработчик управления модерацией чатов в сетке"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🛡️ <b>Управление модерацией сетки #{network_id}</b>\n\n"
        text += "<b>Выберите чат для управления:</b>\n\n"
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                text += f"{i}. <b>{chat_info['chat_title']}</b>\n\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки для каждого чата
        for chat_data in network_chats:
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                builder.add(InlineKeyboardButton(
                    text=f"🛡️ {chat_info['chat_title'][:20]}...",
                    callback_data=f"moderation_chat_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_moderation_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("moderation_chat_"))
async def moderation_chat_callback(callback: types.CallbackQuery):
    """Обработчик выбора чата для управления модерацией"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем информацию о чате
        chat_info = await db.get_chat(chat_id)
        if not chat_info:
            await callback.answer("❌ Чат не найден!")
            return
        
        # Получаем текущие настройки чата
        try:
            chat_obj = await bot.get_chat(chat_id)
            
            # В aiogram 3.x нет прямого метода get_chat_permissions
            # Используем дефолтные значения, но можем попробовать определить состояние
            # по другим признакам
            can_send_messages = True
            can_send_media = True
            can_send_polls = True
            can_send_other = True
            
            # Попробуем определить состояние по типу чата и другим признакам
            if hasattr(chat_obj, 'permissions') and chat_obj.permissions:
                # Если есть информация о правах, используем её
                perms = chat_obj.permissions
                can_send_messages = getattr(perms, 'can_send_messages', True)
                can_send_media = getattr(perms, 'can_send_media_messages', True)
                can_send_polls = getattr(perms, 'can_send_polls', True)
                can_send_other = getattr(perms, 'can_send_other_messages', True)
            
        except Exception as e:
            logger.error(f"Ошибка при получении настроек чата {chat_id}: {e}")
            can_send_messages = True
            can_send_media = True
            can_send_polls = True
            can_send_other = True
        
        text = f"🛡️ <b>Управление модерацией</b>\n\n"
        text += f"<b>Чат:</b> {chat_info['chat_title']}\n\n"
        text += f"<b>Текущие настройки:</b>\n"
        text += f"• 💬 Сообщения: {'✅' if can_send_messages else '❌'}\n"
        text += f"• 🖼️ Медиа: {'✅' if can_send_media else '❌'}\n"
        text += f"• 📊 Опросы: {'✅' if can_send_polls else '❌'}\n"
        text += f"• 🎁 Другое: {'✅' if can_send_other else '❌'}\n\n"
        text += "<b>Выберите действие:</b>"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки управления (без slowmode)
        
        # Кнопка управления медиа (переключатель)
        media_status = "Включено" if can_send_media else "Отключено"
        builder.add(InlineKeyboardButton(
            text=f"🖼️ Медиа: {media_status}",
            callback_data=f"media_toggle_{network_id}_{chat_id}"
        ))
        
        # Кнопка управления сообщениями (переключатель)
        messages_status = "Включено" if can_send_messages else "Отключено"
        builder.add(InlineKeyboardButton(
            text=f"💬 Сообщения: {messages_status}",
            callback_data=f"messages_toggle_{network_id}_{chat_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_moderation_{network_id}"
        ))
        
        builder.adjust(2, 2, 1, 1)
        
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                # Сообщение не изменилось, просто отвечаем на callback
                await callback.answer()
            else:
                raise e
        
    except Exception as e:
        logger.error(f"Ошибка в moderation_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("media_toggle_"))
async def media_toggle_callback(callback: types.CallbackQuery):
    """Обработчик переключения медиа"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем cooldown модерации
        can_act, remaining = check_moderation_cooldown(user_id)
        if not can_act:
            await callback.answer(f"⏱️ Подождите {remaining} секунд перед следующим действием!")
            return
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Переключаем медиа
        try:
            # Получаем текущие права чата
            try:
                chat_obj = await bot.get_chat(chat_id)
                current_permissions = getattr(chat_obj, 'permissions', None)
                
                # Определяем текущее состояние медиа
                if current_permissions:
                    current_media_state = getattr(current_permissions, 'can_send_media_messages', True)
                else:
                    # Если не можем определить, считаем что медиа включено
                    current_media_state = True
                    
            except Exception as e:
                logger.error(f"Ошибка при получении текущих прав чата {chat_id}: {e}")
                # Если не можем получить права, считаем что медиа включено
                current_media_state = True
            
            # Создаем новые права в зависимости от текущего состояния
            if current_media_state:
                # Медиа включено - отключаем
                new_permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True
                )
                success_message = "✅ Медиа отключено!"
            else:
                # Медиа отключено - включаем
                new_permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True
                )
                success_message = "✅ Медиа включено!"
            
            # Устанавливаем новые права
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=new_permissions,
                use_independent_chat_permissions=True
            )
            
            await callback.answer(success_message)
            
            # Возвращаемся к управлению модерацией чата
            await moderation_chat_callback(callback)
            
        except Exception as e:
            if "CHAT_NOT_MODIFIED" in str(e):
                # Если права не изменились, показываем текущее состояние
                if current_media_state:
                    await callback.answer("ℹ️ Медиа уже включено!")
                else:
                    await callback.answer("ℹ️ Медиа уже отключено!")
                await moderation_chat_callback(callback)
            else:
                logger.error(f"Ошибка при переключении медиа: {e}")
                await callback.answer("❌ Ошибка при изменении настроек медиа!")
        
    except Exception as e:
        logger.error(f"Ошибка в media_toggle_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("messages_toggle_"))
async def messages_toggle_callback(callback: types.CallbackQuery):
    """Обработчик переключения сообщений"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем cooldown модерации
        can_act, remaining = check_moderation_cooldown(user_id)
        if not can_act:
            await callback.answer(f"⏱️ Подождите {remaining} секунд перед следующим действием!")
            return
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Переключаем сообщения
        try:
            # Получаем текущие права чата
            try:
                chat_obj = await bot.get_chat(chat_id)
                current_permissions = getattr(chat_obj, 'permissions', None)
                
                # Определяем текущее состояние сообщений
                if current_permissions:
                    current_messages_state = getattr(current_permissions, 'can_send_messages', True)
                else:
                    # Если не можем определить, считаем что сообщения включены
                    current_messages_state = True
                    
            except Exception as e:
                logger.error(f"Ошибка при получении текущих прав чата {chat_id}: {e}")
                # Если не можем получить права, считаем что сообщения включены
                current_messages_state = True
            
            # Создаем новые права в зависимости от текущего состояния
            if current_messages_state:
                # Сообщения включены - отключаем (закрываем чат)
                new_permissions = ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True
                )
                success_message = "✅ Сообщения отключены! (Чат закрыт)"
            else:
                # Сообщения отключены - включаем (открываем чат)
                new_permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True
                )
                success_message = "✅ Сообщения включены! (Чат открыт)"
            
            # Устанавливаем новые права
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=new_permissions,
                use_independent_chat_permissions=True
            )
            
            await callback.answer(success_message)
            
            # Возвращаемся к управлению модерацией чата
            await moderation_chat_callback(callback)
            
        except Exception as e:
            if "CHAT_NOT_MODIFIED" in str(e):
                # Если права не изменились, показываем текущее состояние
                if current_messages_state:
                    await callback.answer("ℹ️ Сообщения уже включены! (Чат открыт)")
                else:
                    await callback.answer("ℹ️ Сообщения уже отключены! (Чат закрыт)")
                await moderation_chat_callback(callback)
            else:
                logger.error(f"Ошибка при переключении сообщений: {e}")
                await callback.answer("❌ Ошибка при изменении настроек сообщений!")
        
    except Exception as e:
        logger.error(f"Ошибка в messages_toggle_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_sync_"))
async def net_sync_callback(callback: types.CallbackQuery):
    """Обработчик синхронизации настроек между чатами в сетке"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        if len(network_chats) < 2:
            await callback.answer("❌ Для синхронизации нужно минимум 2 чата в сетке!")
            return
        
        text = f"⚙️ <b>Синхронизация настроек сетки #{network_id}</b>\n\n"
        text += "Выберите исходный чат (откуда копировать настройки):\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat_data in enumerate(network_chats):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                builder.add(InlineKeyboardButton(
                    text=f"{i+1}. {chat_info['chat_title']}{primary_mark}",
                    callback_data=f"sync_source_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_sync_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_stats_"))
async def net_stats_callback(callback: types.CallbackQuery):
    """Обработчик подробной статистики сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"📊 <b>Подробная статистика сетки #{network_id}</b>\n\n"
        
        # Общая статистика
        total_messages_today = 0
        total_messages_week = 0
        total_members = 0
        active_users_today = set()
        
        for chat_data in network_chats:
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if not chat_info:
                continue
            
            # Статистика за сегодня
            messages_today = await db.get_today_message_count(chat_id)
            total_messages_today += messages_today
            
            # Статистика за неделю
            week_stats = await db.get_daily_stats(chat_id, 7)
            messages_week = sum(stat['message_count'] for stat in week_stats)
            total_messages_week += messages_week
            
            # Активные пользователи за сегодня
            top_users = await db.get_top_users_today(chat_id, 100)
            for user in top_users:
                active_users_today.add(user['user_id'])
            
            # Количество участников
            try:
                member_count = await bot.get_chat_member_count(chat_id)
                total_members += member_count
            except:
                pass
        
        text += f"📈 <b>Общая статистика:</b>\n"
        text += f"• Сообщений сегодня: {total_messages_today}\n"
        text += f"• Сообщений за неделю: {total_messages_week}\n"
        text += f"• Активных пользователей сегодня: {len(active_users_today)}\n"
        text += f"• Всего участников: {total_members if total_members > 0 else '?'}\n\n"
        
        # Статистика по чатам
        text += f"📋 <b>По чатам:</b>\n"
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                messages_today = await db.get_today_message_count(chat_id)
                week_stats = await db.get_daily_stats(chat_id, 7)
                messages_week = sum(stat['message_count'] for stat in week_stats)
                
                try:
                    member_count = await bot.get_chat_member_count(chat_id)
                except:
                    member_count = "?"
                
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"\n{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                text += f"   📊 Сегодня: {messages_today} | За неделю: {messages_week}\n"
                text += f"   👥 Участников: {member_count}\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_stats_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("net_delete_"))
async def net_delete_callback(callback: types.CallbackQuery):
    """Обработчик удаления сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🗑️ <b>Удаление сетки #{network_id}</b>\n\n"
        text += f"⚠️ <b>Внимание!</b> Это действие удалит сетку и все связи между чатами.\n\n"
        text += f"Чаты в сетке ({len(network_chats)}):\n"
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"{i}. {chat_info['chat_title']}{primary_mark}\n"
        
        text += f"\n<b>Подтвердите удаление, нажав на кнопку ниже</b>"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить сетку",
            callback_data=f"delete_confirm_{network_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"delete_cancel_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в net_delete_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_confirm_"))
async def delete_confirm_callback(callback: types.CallbackQuery):
    """Обработчик подтверждения удаления сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            philosophical_messages = [
                "🌌 Только создатель может разрушить то, что создал...",
                "🔒 Сети создаются владельцами, и только они могут их разорвать...",
                "⚡ Сила разрушения принадлежит лишь тому, кто имел силу созидания...",
                "🌊 Только капитан может потопить свой корабль...",
                "🏰 Ключи от крепости есть только у её строителя...",
                "🎭 Только режиссер может опустить занавес...",
                "🌅 Только тот, кто встречал рассвет, может провожать закат..."
            ]
            import random
            message = random.choice(philosophical_messages)
            await callback.answer(message)
            return
        
        # Удаляем сетку
        success = await network_db.delete_network(network_id)
        if success:
            await callback.message.edit_text("✅ Сетка успешно удалена!")
        else:
            await callback.message.edit_text("❌ Ошибка при удалении сетки!")
        
    except Exception as e:
        logger.error(f"Ошибка в delete_confirm_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_cancel_"))
async def delete_cancel_callback(callback: types.CallbackQuery):
    """Обработчик отмены удаления сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            philosophical_messages = [
                "🌌 Только создатель может отменить то, что начал...",
                "🔒 Решения о судьбе сети принимает только её владелец...",
                "⚡ Только тот, кто имел право начать, имеет право остановиться...",
                "🌊 Только капитан может изменить курс своего корабля...",
                "🏰 Ключи от крепости есть только у её строителя...",
                "🎭 Только режиссер может изменить сценарий...",
                "🌅 Только тот, кто встречал рассвет, может решить о закате..."
            ]
            import random
            message = random.choice(philosophical_messages)
            await callback.answer(message)
            return
        
        # Возвращаемся к просмотру сетки
        await net_view_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в delete_cancel_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_source_"))
async def sync_source_callback(callback: types.CallbackQuery):
    """Обработчик выбора исходного чата для синхронизации"""
    try:
        # Парсим данные: sync_source_{network_id}_{source_chat_id}
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        if len(network_chats) < 2:
            await callback.answer("❌ Для синхронизации нужно минимум 2 чата в сетке!")
            return
        
        # Находим исходный чат
        source_chat_info = None
        for chat_data in network_chats:
            if chat_data['chat_id'] == source_chat_id:
                chat_info = await db.get_chat(chat_data['chat_id'])
                if chat_info:
                    source_chat_info = {
                        'chat_id': chat_data['chat_id'],
                        'title': chat_info['chat_title'],
                        'is_primary': chat_data['is_primary']
                    }
                break
        
        if not source_chat_info:
            await callback.answer("❌ Исходный чат не найден!")
            return
        
        # Получаем целевые чаты (все кроме исходного)
        target_chats = []
        for chat_data in network_chats:
            if chat_data['chat_id'] != source_chat_id:
                chat_info = await db.get_chat(chat_data['chat_id'])
                if chat_info:
                    target_chats.append({
                        'chat_id': chat_data['chat_id'],
                        'title': chat_info['chat_title'],
                        'is_primary': chat_data['is_primary']
                    })
        
        if not target_chats:
            await callback.answer("❌ Нет чатов для синхронизации!")
            return
        
        primary_mark = " 👑" if source_chat_info['is_primary'] else ""
        text = f"⚙️ **Синхронизация настроек**\n\n"
        text += f"📤 **Исходный чат:** {source_chat_info['title']}{primary_mark}\n\n"
        text += f"📥 **Целевые чаты:**\n"
        
        for i, chat in enumerate(target_chats, 1):
            primary_mark = " 👑" if chat['is_primary'] else ""
            text += f"{i}. {chat['title']}{primary_mark}\n"
        
        text += f"\n**Выберите настройки для синхронизации:**"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки выбора настроек
        builder.add(InlineKeyboardButton(
            text="⚠️ Настройки варнов",
            callback_data=f"sync_warns_{network_id}_{source_chat_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="👥 Права рангов",
            callback_data=f"sync_ranks_{network_id}_{source_chat_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="📊 Настройки статистики",
            callback_data=f"sync_stats_{network_id}_{source_chat_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔄 Все настройки",
            callback_data=f"sync_all_{network_id}_{source_chat_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_sync_{network_id}"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в sync_source_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_warns_"))
async def sync_warns_callback(callback: types.CallbackQuery):
    """Обработчик синхронизации настроек варнов"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем настройки варнов из исходного чата
        source_settings = await moderation_db.get_warn_settings(source_chat_id)
        
        # Получаем целевые чаты
        network_chats = await network_db.get_network_chats(network_id)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        synced_count = 0
        for chat_data in target_chats:
            try:
                await moderation_db.update_warn_settings(
                    chat_data['chat_id'],
                    warn_limit=source_settings['warn_limit'],
                    punishment_type=source_settings['punishment_type'],
                    mute_duration=source_settings['mute_duration']
                )
                synced_count += 1
            except Exception as e:
                logger.error(f"Ошибка при синхронизации варнов для чата {chat_data['chat_id']}: {e}")
        
        await callback.message.edit_text(
            f"✅ **Синхронизация настроек варнов завершена!**\n\n"
            f"📤 Исходный чат: {source_chat_id}\n"
            f"📥 Синхронизировано чатов: {synced_count}\n\n"
            f"**Настройки:**\n"
            f"• Лимит варнов: {source_settings['warn_limit']}\n"
            f"• Наказание: {source_settings['punishment_type']}\n"
            f"• Время мута: {source_settings['mute_duration'] or 'Не установлено'}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в sync_warns_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_ranks_"))
async def sync_ranks_callback(callback: types.CallbackQuery):
    """Обработчик синхронизации прав рангов"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем права рангов из исходного чата
        source_permissions = {}
        for rank in [1, 2, 3, 4, 5]:
            permissions = await db.get_all_rank_permissions(source_chat_id, rank)
            source_permissions[rank] = permissions
        
        # Получаем целевые чаты
        network_chats = await network_db.get_network_chats(network_id)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        synced_count = 0
        for chat_data in target_chats:
            try:
                # Копируем права для каждого ранга
                for rank, permissions in source_permissions.items():
                    for permission_type, value in permissions.items():
                        await db.set_rank_permission(chat_data['chat_id'], rank, permission_type, value)
                synced_count += 1
            except Exception as e:
                logger.error(f"Ошибка при синхронизации прав для чата {chat_data['chat_id']}: {e}")
        
        await callback.message.edit_text(
            f"✅ **Синхронизация прав рангов завершена!**\n\n"
            f"📤 Исходный чат: {source_chat_id}\n"
            f"📥 Синхронизировано чатов: {synced_count}\n\n"
            f"**Синхронизированы права для всех рангов:**\n"
            f"• Владелец (1)\n"
            f"• Администратор (2)\n"
            f"• Старший модератор (3)\n"
            f"• Младший модератор (4)\n"
            f"• Пользователь (5)",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в sync_ranks_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_stats_"))
async def sync_stats_callback(callback: types.CallbackQuery):
    """Обработчик синхронизации настроек статистики"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем настройки статистики из исходного чата
        source_settings = await db.get_chat_stat_settings(source_chat_id)
        
        # Получаем целевые чаты
        network_chats = await network_db.get_network_chats(network_id)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        synced_count = 0
        for chat_data in target_chats:
            try:
                await db.set_chat_stats_enabled(chat_data['chat_id'], source_settings['stats_enabled'])
                synced_count += 1
            except Exception as e:
                logger.error(f"Ошибка при синхронизации статистики для чата {chat_data['chat_id']}: {e}")
        
        stats_status = "включена" if source_settings['stats_enabled'] else "отключена"
        await callback.message.edit_text(
            f"✅ **Синхронизация настроек статистики завершена!**\n\n"
            f"📤 Исходный чат: {source_chat_id}\n"
            f"📥 Синхронизировано чатов: {synced_count}\n\n"
            f"**Настройка:**\n"
            f"• Статистика: {stats_status}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в sync_stats_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_all_"))
async def sync_all_callback(callback: types.CallbackQuery):
    """Обработчик синхронизации всех настроек"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        # Получаем все настройки из исходного чата
        warn_settings = await moderation_db.get_warn_settings(source_chat_id)
        stats_settings = await db.get_chat_stat_settings(source_chat_id)
        
        # Получаем права рангов
        rank_permissions = {}
        for rank in [1, 2, 3, 4, 5]:
            permissions = await db.get_all_rank_permissions(source_chat_id, rank)
            rank_permissions[rank] = permissions
        
        # Получаем целевые чаты
        network_chats = await network_db.get_network_chats(network_id)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        synced_count = 0
        for chat_data in target_chats:
            try:
                # Синхронизируем настройки варнов
                await moderation_db.update_warn_settings(
                    chat_data['chat_id'],
                    warn_limit=warn_settings['warn_limit'],
                    punishment_type=warn_settings['punishment_type'],
                    mute_duration=warn_settings['mute_duration']
                )
                
                # Синхронизируем настройки статистики
                await db.set_chat_stats_enabled(chat_data['chat_id'], stats_settings['stats_enabled'])
                
                # Синхронизируем права рангов
                for rank, permissions in rank_permissions.items():
                    for permission_type, value in permissions.items():
                        await db.set_rank_permission(chat_data['chat_id'], rank, permission_type, value)
                
                synced_count += 1
            except Exception as e:
                logger.error(f"Ошибка при полной синхронизации для чата {chat_data['chat_id']}: {e}")
        
        stats_status = "включена" if stats_settings['stats_enabled'] else "отключена"
        await callback.message.edit_text(
            f"✅ **Полная синхронизация настроек завершена!**\n\n"
            f"📤 Исходный чат: {source_chat_id}\n"
            f"📥 Синхронизировано чатов: {synced_count}\n\n"
            f"**Синхронизированы:**\n"
            f"• ⚠️ Настройки варнов\n"
            f"• 👥 Права всех рангов\n"
            f"• 📊 Настройки статистики ({stats_status})\n\n"
            f"Все настройки успешно скопированы!",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Ошибка в sync_all_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


# Обработчики callback'ов для панельки часовых поясов
@dp.callback_query(F.data.startswith("timezone_"))
async def timezone_callback_handler(callback: types.CallbackQuery):
    """Обработчик callback'ов панельки часовых поясов"""
    user = callback.from_user
    data = callback.data
    
    # Периодически очищаем старые записи
    cleanup_old_timezone_panels()
    
    # Проверяем, что пользователь нажимает на свою панельку
    message_id = callback.message.message_id
    panel_owner_id = timezone_panel_owners.get(message_id)
    
    # Если владелец панельки не найден, считаем что панелька принадлежит текущему пользователю
    # (для обратной совместимости со старыми панельками)
    if panel_owner_id is None:
        timezone_panel_owners[message_id] = user.id
        panel_owner_id = user.id
    
    # Если пользователь пытается нажать на чужую панельку
    if panel_owner_id != user.id:
        philosophical_messages = [
            "🧘 Чужие настройки — как чужие мысли: лучше не вмешиваться",
            "🌸 Каждый сам хозяин своего времени и пространства",
            "🎭 Не стоит играть с чужими часами — у каждого свой ритм жизни",
            "🌊 Как река не может течь в чужом русле, так и ты не можешь настраивать чужое время",
            "🍃 Мудрость в том, чтобы знать границы: это не твоя панелька",
            "⚖️ Уважение к чужому выбору — основа гармонии в цифровом мире",
            "🌟 Каждый пользователь — целая вселенная со своими настройками",
            "🎨 Не стоит рисовать на чужом холсте времени"
        ]
        
        message = random.choice(philosophical_messages)
        await callback.answer(message, show_alert=False)  # Toast вместо alert
        return
    
    # Проверяем кулдаун
    can_act, remaining = check_timezone_cooldown(user.id)
    if not can_act:
        await callback.answer(
            f"⏰ Подождите {remaining} секунд перед следующим действием",
            show_alert=False  # Toast вместо alert
        )
        return
    
    try:
        if data == "timezone_current":
            # Показать текущий часовой пояс
            current_offset = await timezone_db.get_user_timezone(user.id)
            current_tz = timezone_db.format_timezone_offset(current_offset)
            await callback.answer(f"Текущий часовой пояс: {current_tz}")
            
        elif data.startswith("timezone_set_"):
            # Установить конкретный часовой пояс
            offset = int(data.split("_")[2])
            success = await timezone_db.set_user_timezone(user.id, offset)
            if success:
                tz_label = timezone_db.format_timezone_offset(offset)
                await callback.answer(f"✅ Установлен: {tz_label}")
                # Обновляем панельку
                await update_timezone_panel(callback, user.id)
            else:
                await callback.answer("❌ Ошибка при установке часового пояса", show_alert=False)
                
        elif data == "timezone_decrease":
            # Уменьшить на 1 час
            current_offset = await timezone_db.get_user_timezone(user.id)
            new_offset = max(-12, current_offset - 1)
            success = await timezone_db.set_user_timezone(user.id, new_offset)
            if success:
                tz_label = timezone_db.format_timezone_offset(new_offset)
                await callback.answer(f"⏪ Установлен: {tz_label}")
                # Обновляем панельку
                await update_timezone_panel(callback, user.id)
            else:
                await callback.answer("❌ Ошибка при изменении часового пояса", show_alert=False)
                
        elif data == "timezone_increase":
            # Увеличить на 1 час
            current_offset = await timezone_db.get_user_timezone(user.id)
            new_offset = min(14, current_offset + 1)
            success = await timezone_db.set_user_timezone(user.id, new_offset)
            if success:
                tz_label = timezone_db.format_timezone_offset(new_offset)
                await callback.answer(f"⏩ Установлен: {tz_label}")
                # Обновляем панельку
                await update_timezone_panel(callback, user.id)
            else:
                await callback.answer("❌ Ошибка при изменении часового пояса", show_alert=False)
                
        elif data == "timezone_reset":
            # Сбросить на UTC+3
            success = await timezone_db.set_user_timezone(user.id, 3)
            if success:
                await callback.answer("🔄 Сброшено на UTC+3")
                # Обновляем панельку
                await update_timezone_panel(callback, user.id)
            else:
                await callback.answer("❌ Ошибка при сбросе часового пояса", show_alert=False)
                
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике часовых поясов: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=False)


# Callback handlers для голосования за мут
@dp.callback_query(F.data.startswith("votemute_"))
async def votemute_callback_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик callback'ов панели голосования за мут"""
    user = callback.from_user
    data = callback.data
    
    try:
        if data == "votemute_cancel":
            # Отмена создания голосования
            await state.clear()
            await callback.message.edit_text("Создание голосования отменено")
            await safe_answer_callback(callback, "Голосование отменено")
            
        elif data.startswith("votemute_duration_"):
            # Изменение длительности мута
            duration = int(data.split("_")[2])
            await state.update_data(mute_duration=duration)
            await show_duration_menu(callback, state)
            await safe_answer_callback(callback, f"Время мута: {duration} мин")
            
        elif data.startswith("votemute_reqvotes_"):
            # Изменение количества голосов
            votes = int(data.split("_")[2])
            await state.update_data(required_votes=votes)
            await show_votes_menu(callback, state)
            await safe_answer_callback(callback, f"Нужно голосов: {votes}")
            
        elif data.startswith("votemute_votetime_"):
            # Изменение времени голосования
            time_minutes = int(data.split("_")[2])
            await state.update_data(vote_duration=time_minutes)
            await show_time_menu(callback, state)
            await safe_answer_callback(callback, f"Время голосования: {time_minutes} мин")
            
        elif data.startswith("votemute_pin_"):
            # Переключение закрепа сообщения
            pin_value = data.split("_")[2] == "True"
            await state.update_data(pin_message=pin_value)
            await show_pin_menu(callback, state)
            await safe_answer_callback(callback, f"Закреп: {'Да' if pin_value else 'Нет'}")
            
        elif data == "votemute_quick":
            # Быстрое создание голосования
            await state.update_data(
                mute_duration=30,  # 30 минут
                required_votes=5,  # 5 голосов
                vote_duration=5,   # 5 минут
                pin_message=False  # Без закрепа
            )
            await show_votemute_config_panel_edit(callback, state)
            await safe_answer_callback(callback, "Быстрые настройки применены")
            
        elif data == "votemute_start":
            # Создание голосования
            await create_votemute_vote(callback, state)
            
        elif data == "votemute_menu_duration":
            # Меню выбора времени мута
            await show_duration_menu(callback, state)
            
        elif data == "votemute_menu_votes":
            # Меню выбора количества голосов
            await show_votes_menu(callback, state)
            
        elif data == "votemute_menu_time":
            # Меню выбора времени голосования
            await show_time_menu(callback, state)
            
        elif data == "votemute_menu_pin":
            # Меню выбора закрепа
            await show_pin_menu(callback, state)
            
        elif data == "votemute_back":
            # Возврат в главное меню
            await show_votemute_config_panel_edit(callback, state)
            
        else:
            await safe_answer_callback(callback, "Неизвестная команда")
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике голосования за мут: {e}")
        if "FloodWaitError" in str(type(e)):
            await safe_answer_callback(callback, "⏰ Слишком много запросов, попробуйте позже", show_alert=True)
        else:
            await safe_answer_callback(callback, "Произошла ошибка")


async def create_votemute_vote(callback: types.CallbackQuery, state: FSMContext):
    """Создать голосование за мут"""
    data = await state.get_data()
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    try:
        # Устанавливаем кулдаун
        await votemute_db.set_cooldown(chat_id)
        
        # Создаем голосование в БД
        vote_id = await votemute_db.create_vote(
            chat_id=chat_id,
            target_user_id=data['target_user_id'],
            creator_id=user_id,
            mute_duration=data['mute_duration'] * 60,  # Переводим в секунды
            required_votes=data['required_votes'],
            vote_duration=data['vote_duration'],
            is_pinned=data['pin_message'],
            target_username=data['target_username'],
            target_first_name=data['target_first_name'],
            target_last_name=data['target_last_name'],
            creator_username=callback.from_user.username,
            creator_first_name=callback.from_user.first_name,
            creator_last_name=callback.from_user.last_name
        )
        
        # Отправляем сообщение с голосованием
        vote_data = {
            'target_user_id': data['target_user_id'],
            'target_username': data['target_username'],
            'target_first_name': data['target_first_name'],
            'target_last_name': data['target_last_name'],
            'creator_id': user_id,
            'creator_username': callback.from_user.username,
            'creator_first_name': callback.from_user.first_name,
            'creator_last_name': callback.from_user.last_name,
            'mute_duration': data['mute_duration'],
            'required_votes': data['required_votes'],
            'vote_duration': data['vote_duration']
        }
        vote_message = await send_votemute_message(chat_id, vote_id, vote_data)
        
        # Обновляем message_id в БД
        await votemute_db.update_vote_message_id(vote_id, vote_message.message_id)
        
        # Закрепляем сообщение если нужно
        if data['pin_message']:
            try:
                await bot.pin_chat_message(chat_id, vote_message.message_id)
            except Exception as e:
                logger.error(f"Не удалось закрепить сообщение голосования: {e}")
        
        # Запускаем таймер завершения голосования
        asyncio.create_task(votemute_timer(vote_id, data['vote_duration'] * 60))
        
        # Очищаем FSM
        await state.clear()
        
        # Удаляем панель конфигурации
        await callback.message.delete()
        
    except Exception as e:
        logger.error(f"Ошибка при создании голосования: {e}")
        await safe_answer_callback(callback, "Ошибка при создании голосования")


async def send_votemute_message(chat_id: int, vote_id: int, data: dict) -> Message:
    """Отправить сообщение с голосованием"""
    target_name = data['target_first_name'] or f"@{data['target_username']}" if data['target_username'] else f"ID{data['target_user_id']}"
    creator_name = data['creator_first_name'] or f"@{data['creator_username']}" if data['creator_username'] else f"ID{data['creator_id']}"
    
    mute_duration_text = f"{data['mute_duration']} мин" if data['mute_duration'] < 60 else f"{data['mute_duration'] // 60} час"
    
    text = f"""<b>🗳️ Голосование за мут</b>

<i>👤 Нарушитель:</i> {target_name}
<i>⏱️ Время мута:</i> {mute_duration_text}
<i>📊 Голосов для завершения:</i> {data['required_votes']}
<i>⏰ Голосование длится:</i> {data['vote_duration']} мин
<i>👮 Инициатор:</i> {creator_name}

<b>📈 Голоса:</b> За 0 | Против 0"""
    
    # Создаем клавиатуру
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ За (0)",
        callback_data=f"vote_yes_{vote_id}"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Против (0)",
        callback_data=f"vote_no_{vote_id}"
    ))
    builder.adjust(2)
    
    return await bot.send_message(chat_id, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


# Обработчики голосов
@dp.callback_query(F.data.startswith("vote_"))
async def vote_callback_handler(callback: types.CallbackQuery):
    """Обработчик голосов за/против"""
    user = callback.from_user
    data = callback.data
    
    try:
        if data.startswith("vote_yes_") or data.startswith("vote_no_"):
            vote_id = int(data.split("_")[2])
            vote_type = "yes" if data.startswith("vote_yes_") else "no"
            
            # Получаем данные голосования
            vote_data = await votemute_db.get_vote_by_id(vote_id)
            if not vote_data:
                await safe_answer_callback(callback, "Голосование не найдено")
                return
            
            # Проверяем, что голосование еще активно
            if datetime.fromisoformat(vote_data['expires_at']) <= datetime.now():
                await safe_answer_callback(callback, "Голосование завершено")
                return
            
            # Проверяем, что пользователь не создатель и не цель мута
            if user.id == vote_data['creator_id']:
                await safe_answer_callback(callback, "Создатель не может голосовать")
                return
            
            if user.id == vote_data['target_user_id']:
                await safe_answer_callback(callback, "Цель мута не может голосовать")
                return
            
            # Проверяем, что пользователь не модератор (только обычные участники голосуют)
            user_rank = await get_effective_rank(vote_data['chat_id'], user.id)
            if user_rank != RANK_USER:
                await safe_answer_callback(callback, "Модераторы не участвуют в голосовании")
                return
            
            # Добавляем голос
            success = await votemute_db.add_vote(vote_id, user.id, vote_type)
            if not success:
                await safe_answer_callback(callback, "Можно менять голос раз в 30 секунд")
                return
            
            # Получаем обновленные результаты
            results = await votemute_db.get_vote_results(vote_id)
            logger.info(f"Голосование {vote_id}: голос {vote_type} от пользователя {user.id}, результаты: {results}")
            
            # Обновляем сообщение только если голос изменился
            await update_vote_message(vote_data['chat_id'], vote_data['message_id'], vote_data, results)
            
            # Проверяем условия завершения - большинство голосов "за"
            total_votes = results['yes'] + results['no']
            if total_votes >= vote_data['required_votes']:
                if results['yes'] > results['no']:
                    await finish_votemute(vote_id, "success", "Большинство голосов за мут")
                else:
                    await finish_votemute(vote_id, "failed", "Большинство голосов против мута")
            
            await safe_answer_callback(callback, f"Голос за {vote_type} засчитан")
            
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике голосов: {e}")
        if "FloodWaitError" in str(type(e)):
            await safe_answer_callback(callback, "⏰ Слишком много запросов, попробуйте позже", show_alert=True)
        else:
            await safe_answer_callback(callback, "Произошла ошибка")


# Кэш для последних результатов голосования
_vote_cache = {}

async def update_vote_message(chat_id: int, message_id: int, vote_data: dict, results: dict):
    """Обновить сообщение с голосованием"""
    try:
        # Проверяем, изменились ли результаты
        cache_key = f"{chat_id}_{message_id}"
        cached_results = _vote_cache.get(cache_key)
        
        if cached_results and cached_results['yes'] == results['yes'] and cached_results['no'] == results['no']:
            # Результаты не изменились, не обновляем сообщение
            return
        
        # Обновляем кэш
        _vote_cache[cache_key] = results.copy()
        target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" if vote_data['target_username'] else f"ID{vote_data['target_user_id']}"
        creator_name = vote_data['creator_first_name'] or f"@{vote_data['creator_username']}" if vote_data['creator_username'] else f"ID{vote_data['creator_id']}"
        
        mute_duration_text = f"{vote_data['mute_duration'] // 60} мин" if vote_data['mute_duration'] < 3600 else f"{vote_data['mute_duration'] // 3600} час"
        
        text = f"""<b>🗳️ Голосование за мут</b>

<i>👤 Нарушитель:</i> {target_name}
<i>⏱️ Время мута:</i> {mute_duration_text}
<i>📊 Голосов для завершения:</i> {vote_data['required_votes']}
<i>⏰ Голосование длится:</i> {vote_data['vote_duration']} мин
<i>👮 Инициатор:</i> {creator_name}

<b>📈 Голоса:</b> За {results['yes']} | Против {results['no']}"""
        
        # Создаем клавиатуру
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=f"✅ За ({results['yes']})",
            callback_data=f"vote_yes_{vote_data['vote_id']}"
        ))
        builder.add(InlineKeyboardButton(
            text=f"❌ Против ({results['no']})",
            callback_data=f"vote_no_{vote_data['vote_id']}"
        ))
        builder.adjust(2)
        
        # Добавляем небольшую задержку только для обновления голосов, не для навигации
        if "vote_" in str(vote_data.get('vote_id', '')):
            await asyncio.sleep(0.05)
        
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=builder.as_markup(),
                parse_mode=ParseMode.HTML
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified"
            if "message is not modified" not in str(edit_error).lower():
                logger.error(f"Ошибка при редактировании сообщения голосования: {edit_error}")
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения голосования: {e}")




async def finish_votemute(vote_id: int, result: str, reason: str):
    """Завершить голосование"""
    try:
        vote_data = await votemute_db.get_vote_by_id(vote_id)
        if not vote_data:
            return
        
        # Получаем результаты
        results = await votemute_db.get_vote_results(vote_id)
        
        # Переносим в историю и удаляем из активных
        await votemute_db.finish_vote(vote_id, result, reason)
        
        # Обновляем сообщение
        target_name = vote_data['target_first_name'] or f"@{vote_data['target_username']}" if vote_data['target_username'] else f"ID{vote_data['target_user_id']}"
        
        if result == "success":
            # Применяем мут
            mute_until = datetime.now() + timedelta(seconds=vote_data['mute_duration'])
            
            try:
                await bot.restrict_chat_member(
                    chat_id=vote_data['chat_id'],
                    user_id=vote_data['target_user_id'],
                    permissions=types.ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    ),
                    until_date=mute_until
                )
                
                # Сохраняем в базу модерации
                await moderation_db.add_punishment(
                    chat_id=vote_data['chat_id'],
                    user_id=vote_data['target_user_id'],
                    moderator_id=bot.id,  # Системный мут
                    punishment_type="mute",
                    reason="Голосование участников",
                    duration_seconds=vote_data['mute_duration'],
                    expiry_date=mute_until.isoformat(),
                    user_username=vote_data['target_username'],
                    user_first_name=vote_data['target_first_name'],
                    user_last_name=vote_data['target_last_name'],
                    moderator_username="Система",
                    moderator_first_name="Голосование",
                    moderator_last_name=""
                )
                
                # Обновляем репутацию
                penalty = reputation_db.calculate_reputation_penalty('mute', vote_data['mute_duration'])
                await reputation_db.add_recent_punishment(vote_data['target_user_id'], 'mute', vote_data['mute_duration'])
                await reputation_db.update_reputation(vote_data['target_user_id'], penalty)
                
                text = f"""<b>✅ Голосование завершено - пользователь замучен</b>

<i>👤 Нарушитель:</i> {target_name}
<i>⏱️ Время мута:</i> {vote_data['mute_duration'] // 60} мин
<i>📊 Результат:</i> За {results['yes']} | Против {results['no']}
<i>📝 Причина:</i> {reason}"""
                
            except Exception as e:
                logger.error(f"Ошибка при применении мута: {e}")
                text = f"""<b>❌ Голосование завершено - ошибка при применении мута</b>

<i>👤 Нарушитель:</i> {target_name}
<i>📊 Результат:</i> За {results['yes']} | Против {results['no']}
<i>📝 Причина:</i> {reason}"""
        else:
            if result == "failed":
                text = f"""<b>❌ Голосование завершено - большинство против мута</b>

<i>👤 Нарушитель:</i> {target_name}
<i>📊 Результат:</i> За {results['yes']} | Против {results['no']}
<i>📝 Причина:</i> {reason}"""
            else:
                text = f"""<b>⏰ Голосование завершено - мут не применен</b>

<i>👤 Нарушитель:</i> {target_name}
<i>📊 Результат:</i> За {results['yes']} | Против {results['no']}
<i>📝 Причина:</i> {reason}"""
        
        # Открепляем сообщение если было закреплено
        if vote_data['is_pinned']:
            try:
                await bot.unpin_chat_message(chat_id=vote_data['chat_id'], message_id=vote_data['message_id'])
            except Exception as e:
                logger.error(f"Не удалось открепить сообщение: {e}")
        
        # Обновляем сообщение без кнопок
        await bot.edit_message_text(
            chat_id=vote_data['chat_id'],
            message_id=vote_data['message_id'],
            text=text,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при завершении голосования: {e}")


async def votemute_timer(vote_id: int, duration_seconds: int):
    """Таймер завершения голосования"""
    await asyncio.sleep(duration_seconds)
    
    # Проверяем, что голосование еще активно
    vote_data = await votemute_db.get_vote_by_id(vote_id)
    if vote_data:
        # Получаем результаты голосования
        results = await votemute_db.get_vote_results(vote_id)
        
        # Определяем результат на основе большинства голосов
        if results['yes'] > results['no']:
            await finish_votemute(vote_id, "success", "Время истекло - большинство за мут")
        else:
            await finish_votemute(vote_id, "failed", "Время истекло - большинство против мута")


@dp.message(F.left_chat_member)
async def left_chat_member(message: Message):
    """Обработчик удаления бота из чата"""
    # Проверяем, что это именно бот покинул чат
    if message.left_chat_member.id == bot.id:
        # Помечаем чат как неактивный
        await db.remove_chat(message.chat.id)
        logger.info(f"Бот покинул чат {message.chat.id}")


def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    logger.info(f"Получен сигнал {signum}, инициируем остановку...")
    shutdown_event.set()

def setup_signal_handlers():
    """Настройка обработчиков сигналов"""
    try:
        # Для Unix-систем
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("Обработчики сигналов настроены")
    except (ValueError, OSError) as e:
        # Для Windows или других систем где сигналы работают по-другому
        logger.warning(f"Не удалось настроить обработчики сигналов: {e}")
        logger.info("Используем альтернативный способ остановки")


# ========== CALLBACK HANDLERS ДЛЯ СИСТЕМЫ ДРУЗЕЙ ==========

@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    try:
        # Создаем главное меню
        welcome_text, reply_markup = await create_main_menu()
        
        await callback.message.edit_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в main_menu_callback: {e}")
        await callback.answer("❌ Ошибка при обновлении меню")


@dp.callback_query(F.data == "friends_menu")
async def friends_menu_callback(callback: types.CallbackQuery):
    """Меню друзей"""
    try:
        user_id = callback.from_user.id
        
        # Получаем список друзей
        friends = await friends_db.get_friends(user_id)
        friend_count = len(friends)
        
        text = f"👥 <b>Друзья</b> ({friend_count}/5)\n\n"
        
        if friend_count == 0:
            text += "У вас пока нет друзей.\nИспользуйте кнопку ниже, чтобы добавить друга!"
        else:
            text += "Ваши друзья:\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки для каждого друга
        for friend in friends:
            # Получаем информацию о друге
            try:
                friend_info = await db.get_user(friend['user_id'])
                if friend_info:
                    friend_name = friend_info.get('first_name', '')
                    if friend_info.get('last_name'):
                        friend_name += f" {friend_info['last_name']}"
                    friend_name = friend_name.strip() or f"ID{friend['user_id']}"
                    
                    builder.add(InlineKeyboardButton(
                        text=f"👤 {friend_name}",
                        callback_data=f"friend_profile_{friend['user_id']}"
                    ))
            except Exception as e:
                logger.error(f"Ошибка при получении информации о друге {friend['user_id']}: {e}")
                builder.add(InlineKeyboardButton(
                    text=f"👤 ID{friend['user_id']}",
                    callback_data=f"friend_profile_{friend['user_id']}"
                ))
        
        # Кнопка для создания кода
        if friend_count < 5:
            builder.add(InlineKeyboardButton(
                text="➕ Создать код",
                callback_data="add_friend"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text="❌ Лимит друзей (5/5)",
                callback_data="friends_limit_reached"
            ))
        
        # Кнопка "Назад"
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="main_menu"
        ))
        
        # Настраиваем расположение кнопок (по 1 в ряд)
        builder.adjust(1)
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в friends_menu_callback: {e}")
        await callback.answer("❌ Ошибка при загрузке списка друзей")




@dp.callback_query(F.data == "add_friend")
async def add_friend_callback(callback: types.CallbackQuery):
    """Генерация кода для добавления друга"""
    try:
        user_id = callback.from_user.id
        
        # Проверяем лимит друзей
        friend_count = await friends_db.get_friend_count(user_id)
        if friend_count >= 5:
            await callback.answer("❌ Достигнут лимит друзей (5/5)", show_alert=True)
            return
        
        # Генерируем код
        code = await friends_db.generate_friend_code(user_id)
        
        text = f"""
🔐 <b>Код для добавления в друзья</b>

Ваш код: <code>{code}</code>

⏰ <b>Код действителен 10 минут</b>

📋 <b>Как добавить друга:</b>
1. Отправьте этот код другу
2. Друг должен написать в ЛС боту: <code>/addfriend {code}</code>
3. После этого вы станете друзьями!

⚠️ <b>Важно:</b> Код можно использовать только один раз
        """
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад к друзьям",
            callback_data="friends_menu"
        ))
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в add_friend_callback: {e}")
        await callback.answer("❌ Ошибка при генерации кода")


@dp.callback_query(F.data.startswith("friend_profile_"))
async def friend_profile_callback(callback: types.CallbackQuery):
    """Профиль друга"""
    try:
        user_id = callback.from_user.id
        friend_id = int(callback.data.split("_")[2])
        
        # Получаем информацию о друге
        friend_info = await db.get_user(friend_id)
        if not friend_info:
            await callback.answer("❌ Информация о друге не найдена", show_alert=True)
            return
        
        # Формируем имя
        friend_name = friend_info.get('first_name', '')
        if friend_info.get('last_name'):
            friend_name += f" {friend_info['last_name']}"
        friend_name = friend_name.strip() or f"ID{friend_id}"
        
        # Username
        username = friend_info.get('username')
        if username:
            display_name = f"<a href='https://t.me/{username}'>{friend_name}</a>"
        else:
            display_name = friend_name
        
        # Получаем репутацию
        reputation = await reputation_db.get_user_reputation(friend_id)
        reputation_emoji = get_reputation_emoji(reputation)
        
        # Получаем глобальную активность
        global_activity = await db.get_user_global_activity(friend_id)
        
        # Получаем топ-3 чата
        top_chats = await db.get_user_top_chats(friend_id, 3)
        
        # Получаем общие чаты
        common_chats = await db.get_common_chats(user_id, friend_id)
        
        text = f"👤 <b>Профиль друга: {display_name}</b>\n\n"
        text += f"🎯 <b>Репутация:</b> {reputation}/100 {reputation_emoji}\n\n"
        
        # Активность
        text += "📊 <b>Активность:</b>\n"
        if global_activity and (global_activity.get('today', 0) > 0 or global_activity.get('week', 0) > 0):
            text += f"💬 Сегодня: {global_activity.get('today', 0)} сообщений\n"
            text += f"📊 За неделю: {global_activity.get('week', 0)} сообщений\n"
        else:
            text += "📈 Нет активности за последнее время\n"
        
        # Топ чаты
        if top_chats:
            text += "\n🏠 <b>Любимые чаты:</b>\n"
            for i, chat in enumerate(top_chats[:3], 1):
                text += f"{i}. {chat['chat_title']} ({chat['total_messages']} сообщений)\n"
        
        # Общие чаты
        if common_chats:
            text += "\n💬 <b>Общие чаты:</b>\n"
            for chat in common_chats[:5]:  # Показываем до 5 общих чатов
                text += f"• {chat['chat_title']}\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🗑 Удалить из друзей",
            callback_data=f"remove_friend_{friend_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Назад к друзьям",
            callback_data="friends_menu"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в friend_profile_callback: {e}")
        await callback.answer("❌ Ошибка при загрузке профиля друга")


@dp.callback_query(F.data.startswith("remove_friend_"))
async def remove_friend_callback(callback: types.CallbackQuery):
    """Подтверждение удаления друга"""
    try:
        user_id = callback.from_user.id
        friend_id = int(callback.data.split("_")[2])
        
        # Получаем информацию о друге для отображения
        friend_info = await db.get_user(friend_id)
        if not friend_info:
            await callback.answer("❌ Информация о друге не найдена", show_alert=True)
            return
        
        friend_name = friend_info.get('first_name', '')
        if friend_info.get('last_name'):
            friend_name += f" {friend_info['last_name']}"
        friend_name = friend_name.strip() or f"ID{friend_id}"
        
        text = f"❓ <b>Удалить из друзей?</b>\n\n"
        text += f"Вы действительно хотите удалить <b>{friend_name}</b> из списка друзей?\n\n"
        text += "⚠️ Это действие нельзя отменить."
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"confirm_remove_friend_{friend_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"friend_profile_{friend_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в remove_friend_callback: {e}")
        await callback.answer("❌ Ошибка при подготовке удаления")


@dp.callback_query(F.data.startswith("confirm_remove_friend_"))
async def confirm_remove_friend_callback(callback: types.CallbackQuery):
    """Подтверждение удаления друга"""
    try:
        user_id = callback.from_user.id
        friend_id = int(callback.data.split("_")[3])
        
        # Удаляем дружбу
        success = await friends_db.remove_friendship(user_id, friend_id)
        
        if success:
            await callback.answer("✅ Друг удален из списка")
            # Возвращаемся к списку друзей
            await friends_menu_callback(callback)
        else:
            await callback.answer("❌ Ошибка при удалении друга", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка в confirm_remove_friend_callback: {e}")
        await callback.answer("❌ Ошибка при удалении друга")


@dp.callback_query(F.data == "my_profile_private")
async def my_profile_private_callback(callback: types.CallbackQuery):
    """Показ урезанного профиля в ЛС"""
    try:
        user = callback.from_user
        
        # Получаем глобальную активность
        global_activity = await db.get_user_global_activity(user.id)
        reputation = await reputation_db.get_user_reputation(user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        
        # Формируем имя
        full_name = user.first_name or ""
        if user.last_name:
            full_name += f" {user.last_name}"
        full_name = full_name.strip()
        
        if user.username:
            user_name = f"<a href='https://t.me/{user.username}'>{full_name or user.username}</a>"
        else:
            user_name = full_name or f"ID{user.id}"
        
        profile_lines = [
            f"👤 <b>Профиль: {user_name}</b>",
            "",
            f"🎯 <b>Репутация:</b> {reputation}/100 {reputation_emoji}",
            "",
            "📊 <b>Глобальная статистика:</b>"
        ]
        
        if global_activity and (global_activity.get('today', 0) > 0 or global_activity.get('week', 0) > 0):
            today_count = global_activity.get('today', 0)
            week_count = global_activity.get('week', 0)
            profile_lines.extend([
                f"💬 Сегодня: {today_count} сообщений",
                f"📊 За неделю: {week_count} сообщений"
            ])
        else:
            profile_lines.append("📈 Начните общение в чатах для отслеживания статистики")
        
        profile_lines.extend([
            "",
            "💡 <i>Полный профиль с графиком доступен в чатах</i>"
        ])
        
        text = "\n".join(profile_lines)
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Главное меню",
            callback_data="main_menu"
        ))
        
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в my_profile_private_callback: {e}")
        await callback.answer("❌ Ошибка при загрузке профиля")




@dp.callback_query(F.data == "friends_limit_reached")
async def friends_limit_reached_callback(callback: types.CallbackQuery):
    """Обработка нажатия на кнопку лимита друзей"""
    await callback.answer("❌ Достигнут лимит друзей (5/5). Удалите кого-то чтобы добавить нового", show_alert=True)


@dp.callback_query(F.data.startswith("hints_mode_"))
async def hints_mode_callback(callback: types.CallbackQuery):
    """Обработчик изменения режима подсказок"""
    try:
        # Парсим режим из callback_data
        mode = int(callback.data.split("_")[2])
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        
        # Проверяем кулдаун
        can_change, remaining = check_hints_config_cooldown(user_id)
        if not can_change:
            await callback.answer(f"⏰ Изменение настроек доступно через {remaining} секунд", show_alert=True)
            return
        
        # Проверяем права администратора
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status not in ['creator', 'administrator']:
                if await should_show_hint(chat_id, user_id):
                    await callback.answer("❌ Недостаточно прав для изменения настроек", show_alert=True)
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке прав пользователя {user_id} в чате {chat_id}: {e}")
            await callback.answer("❌ Ошибка при проверке прав", show_alert=True)
            return
        
        # Сохраняем новый режим
        success = await db.set_hints_mode(chat_id, mode)
        
        if success:
            text, markup = await build_hints_settings_panel(chat_id, current_mode=mode)
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            await callback.answer("✅ Режим подсказок изменен\n⏰ Следующее изменение возможночерез 60 секунд")
        else:
            await callback.answer("❌ Ошибка при сохранении настроек", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике hints_mode_callback: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


async def send_notification_to_all_chats(notification_text: str, delete_after: int = None):
    """Универсальная функция для отправки уведомлений во все активные чаты"""
    try:
        logger.info("Отправка уведомлений во все чаты...")
        
        # Получаем все активные чаты
        all_chats = await db.get_all_chats_for_update()
        
        # Фильтруем только группы и супергруппы (исключаем личные сообщения и каналы)
        chats = [
            chat for chat in all_chats 
            if chat.get('chat_type') in ['group', 'supergroup']
        ]
        
        logger.info(
            f"Найдено {len(chats)} групп/супергрупп для отправки уведомлений "
            f"(всего чатов: {len(all_chats)})"
        )
        
        if not chats:
            logger.info("Нет активных групп для отправки уведомлений")
            return
        
        success_count = 0
        error_count = 0
        rate_limit_count = 0
        
        # Telegram API ограничения:
        # - Максимум 30 сообщений в секунду в разные чаты
        # - Используем консервативную задержку: 0.05 секунды = ~20 сообщений/сек
        delay_between_messages = 0.05
        
        # Семафор для ограничения параллельных запросов (максимум 5 одновременно)
        semaphore = asyncio.Semaphore(5)
        
        async def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
            """Удаляет сообщение через указанное количество секунд"""
            try:
                await asyncio.sleep(delay)
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.debug(f"Сообщение удалено из чата {chat_id}")
            except Exception as e:
                # Игнорируем ошибки удаления (сообщение уже удалено, нет прав и т.д.)
                logger.debug(f"Не удалось удалить сообщение из чата {chat_id}: {e}")
        
        async def send_to_chat(chat_id: int):
            """Отправка сообщения в один чат с обработкой ошибок"""
            nonlocal success_count, error_count, rate_limit_count
            
            async with semaphore:
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    try:
                        message = await bot.send_message(
                            chat_id=chat_id,
                            text=notification_text,
                            parse_mode=ParseMode.HTML
                        )
                        success_count += 1
                        
                        # Запускаем задачу удаления сообщения только если указано время (delete_after не None и > 0)
                        # Для сообщений о выключении и обновлении (--up, --newup) delete_after=None, поэтому они не удаляются
                        if delete_after is not None and delete_after > 0:
                            asyncio.create_task(delete_message_after_delay(chat_id, message.message_id, delete_after))
                        
                        return
                    except Exception as e:
                        error_str = str(e).lower()
                        
                        # Обработка rate limit (429 Too Many Requests)
                        if "429" in error_str or "too many requests" in error_str or "retry after" in error_str:
                            rate_limit_count += 1
                            if attempt < max_retries - 1:
                                # Экспоненциальный backoff: 1, 2, 4 секунды
                                wait_time = retry_delay * (2 ** attempt)
                                logger.debug(f"Rate limit для чата {chat_id}, ожидание {wait_time} сек перед повтором")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                logger.warning(f"Превышен rate limit для чата {chat_id} после {max_retries} попыток")
                                error_count += 1
                                return
                        
                        # Другие ошибки (чат недоступен, бот удален и т.д.)
                        if attempt == 0:  # Логируем только при первой попытке
                            logger.debug(f"Не удалось отправить уведомление в чат {chat_id}: {e}")
                        error_count += 1
                        return
        
        # Отправляем сообщения с задержкой между ними
        for i, chat in enumerate(chats):
            chat_id = chat['chat_id']
            await send_to_chat(chat_id)
            
            # Задержка между отправками (кроме последнего сообщения)
            if i < len(chats) - 1:
                await asyncio.sleep(delay_between_messages)
        
        logger.info(
            f"Уведомления отправлены: успешно {success_count}, ошибок {error_count}, "
            f"rate limit {rate_limit_count} (всего чатов: {len(chats)})"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")


async def send_test_mode_notification():
    """Отправка уведомления о тестовом режиме во все активные чаты"""
    notification_text = (
        "⚠️ Бот запускается в тестовом режиме.\n"
        "Возможны ошибки в работе!\n\n"
        "<i>Удалю это сообщение через минуту</i>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=60)


async def send_shutdown_notification():
    """Отправка уведомления о выключении бота для обновления"""
    notification_text = (
        "🔧 <b>Уведомление об обновлении</b>\n\n"
        "Бот выключается для загрузки обновления.\n"
        "Это может занять до 10 минут.\n\n"
        "Подробности читайте на сайте: <a href=\"https://pixel-ut.pro\">pixel-ut.pro</a>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=None)


async def send_update_notification():
    """Отправка уведомления об обновлении бота"""
    notification_text = (
        "✅ <b>Обновление 1.8 вышло! </b>\n\n"
        "Добавлены настройки видимости в топе, отображения, фильтров и частных чатов.\n\n"
        "Ссылка: <a href=\"https://pixel-ut.pro/updates\">pixel-ut.pro</a>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=None)


def print_startup_banner():
    """Выводит ASCII-арт при запуске бота"""
    banner = """
╔═════════════════════════════════════════════╗
║                                             ║
║     ██████╗ ██╗██╗  ██╗███████╗██║          ║
║     ██╔══██╗██║╚██╗██╔╝██╔════╝██║          ║
║     ██████╔╝██║ ╚███╔╝ █████╗  ██║          ║
║     ██╔═══╝ ██║ ██╔██╗ ██╔══╝  ██║          ║
║     ██║     ██║██╔╝ ██╗███████╗╚██████╗     ║
║     ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝     ║
║                                             ║
║                                             ║    
║ Telegram Bot           by GlebSoloProjects  ║
║ Version: 1.10          https://pixel-ut.pro ║
╚═════════════════════════════════════════════╝
    """
    print(banner)


def print_success_message():
    """Выводит сообщение об успешном запуске"""
    success_msg = """
╔═════════════════╗
║                 ║
║ УСПЕШНЫЙ ЗАПУСК ║
║          V 1.10 ║
╚═════════════════╝

    """
    print(success_msg)


async def main(test_mode: bool = False):
    """Основная функция запуска бота"""
    # Устанавливаем обработчики сигналов
    setup_signal_handlers()
    
    # Выводим баннер при запуске
    print_startup_banner()
    
    try:
        # Инициализируем базы данных
        await db.init_db()
        
        # Проверяем целостность основной базы данных
        logger.info("Проверка целостности базы данных...")
        is_integrity_ok = await db.check_integrity()
        if not is_integrity_ok:
            logger.warning("Обнаружено повреждение базы данных. Запуск автоматического восстановления...")
            recovery_success = await db.auto_recover_if_needed()
            if recovery_success:
                logger.info("База данных успешно восстановлена")
                # Повторная инициализация после восстановления
                await db.init_db()
            else:
                logger.error("Не удалось восстановить базу данных. Бот может работать некорректно.")
        else:
            logger.info("Целостность базы данных проверена: OK")
        
        await moderation_db.init_db()
        await reputation_db.init_db()
        await network_db.init_db()
        await votemute_db.init_db()
        await friends_db.init_db()
        await raid_protection_db.init_db()
        logger.info("Базы данных инициализированы")
        
        # Инициализируем JSON-файлы настроек
        init_json_files()
        
        # Инициализируем систему защиты от рейдов
        raid_protection.set_bot(bot)
        logger.info("Система защиты от рейдов инициализирована")
        
        # Очистка дубликатов чатов (однократно при запуске)
        await db.cleanup_duplicate_chats()
        logger.info("Дубликаты чатов очищены")
        
        # Очищаем старые записи статистики (старше 7 дней)
        await db.cleanup_old_stats(7)
        await db.cleanup_old_user_stats(7)
        logger.info("Старые записи статистики очищены")
        
        # Очищаем истекшие наказания
        expired_count = await moderation_db.cleanup_expired_punishments()
        logger.info(f"Очищено {expired_count} истекших наказаний")
        
        # Очищаем истекшие коды друзей
        expired_codes = await friends_db.cleanup_expired_codes()
        logger.info(f"Очищено {expired_codes} истекших кодов друзей")
        
        # Очищаем старые записи активности защиты от рейдов
        await raid_protection_db.cleanup_old_activity(1)
        await raid_protection_db.cleanup_old_joins(2)
        await raid_protection_db.cleanup_old_deleted_messages(5)
        logger.info("Старые записи защиты от рейдов очищены")
        
        # Отправляем уведомления о тестовом режиме, если указан флаг --test
        if test_mode:
            await send_test_mode_notification()
        
        # Запускаем планировщик задач
        scheduler_task = asyncio.create_task(scheduler.start())
        logger.info("Планировщик автоматических задач запущен")
        
        logger.info("Задача очистки истекших голосований добавлена в планировщик")
        
        # Запускаем бота
        logger.info(f"Запуск бота {BOT_NAME}...")
        
        # Создаем задачу для polling
        polling_task = asyncio.create_task(dp.start_polling(bot))
        
        # Небольшая задержка для проверки успешного запуска
        await asyncio.sleep(1)
        
        # Проверяем, что polling не завершился с ошибкой сразу
        if not polling_task.done():
            print_success_message()
        
        # Ждем сигнала остановки или завершения polling
        done, pending = await asyncio.wait(
            [polling_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Отменяем pending задачи
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        logger.info("Остановка бота...")
        
        # Принудительно останавливаем все системы разом
        try:
            # Останавливаем планировщик
            scheduler.running = False
            for task in scheduler.tasks:
                task.cancel()
            
            # Закрываем HTTP-сессию
            await bot.session.close()
            
            logger.info("✓ Бот остановлен")
        except:
            # Игнорируем все ошибки при остановке
            pass


async def send_notifications_and_exit(notification_type: str):
    """Отправляет уведомления и завершает работу бота"""
    try:
        # Инициализируем базы данных
        await db.init_db()
        logger.info("База данных инициализирована")
        
        # Отправляем уведомления и ждем завершения рассылки
        if notification_type == "shutdown":
            logger.info("Начинаем рассылку уведомлений о выключении...")
            await send_shutdown_notification()
            logger.info("✓ Все уведомления о выключении отправлены. Завершение работы...")
        elif notification_type == "update":
            logger.info("Начинаем рассылку уведомлений об обновлении...")
            await send_update_notification()
            logger.info("✓ Все уведомления об обновлении отправлены. Завершение работы...")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")
    finally:
        # Закрываем соединение с ботом
        try:
            await bot.session.close()
            logger.info("Соединение с Telegram API закрыто")
        except Exception as e:
            logger.debug(f"Ошибка при закрытии соединения: {e}")
        
        logger.info("Работа бота завершена")


if __name__ == "__main__":
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description='Запуск Telegram бота PIXEL')
    parser.add_argument('--test', action='store_true', 
                       help='Запустить бота в тестовом режиме (отправит уведомления во все чаты)')
    parser.add_argument('--up', action='store_true',
                       help='Отправить уведомление о выключении для обновления и завершить работу')
    parser.add_argument('--newup', action='store_true',
                       help='Отправить уведомление об обновлении и запустить бота')
    args = parser.parse_args()
    
    try:
        if args.up:
            # Отправляем уведомление о выключении и завершаем работу
            logger.info("Режим --up: отправка уведомлений о выключении...")
            asyncio.run(send_notifications_and_exit("shutdown"))
        elif args.newup:
            # Отправляем уведомление об обновлении и запускаем бота
            logger.info("Режим --newup: отправка уведомлений об обновлении...")
            # Инициализируем базу данных
            async def send_update_and_start():
                await db.init_db()
                await send_update_notification()
                logger.info("Уведомления об обновлении отправлены. Запуск бота...")
                # Запускаем бота после отправки уведомлений
                await main(test_mode=False)
            asyncio.run(send_update_and_start())
        else:
            # Обычный запуск
            asyncio.run(main(test_mode=args.test))
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
