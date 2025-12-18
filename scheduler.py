"""
Модуль для автоматических задач бота PIXEL
"""
import asyncio
import logging
import time
from datetime import datetime

from database import db
from moderation_db import moderation_db
from reputation_db import reputation_db
from network_db import network_db
from config import DEBUG
logger = logging.getLogger(__name__)


# Lazy import для raid_protection_db, чтобы избежать циклических импортов
def get_raid_protection_db():
    """Получить экземпляр базы данных защиты от рейдов"""
    from raid_protection_db import raid_protection_db
    return raid_protection_db


class TaskScheduler:
    """Планировщик автоматических задач"""
    
    def __init__(self, bot_instance=None, max_concurrent_chats=10):
        self.running = False
        self.tasks = []
        self.bot = bot_instance
        # Семафор для ограничения одновременных операций с чатами (защита от rate limit)
        self.chat_semaphore = asyncio.Semaphore(max_concurrent_chats)
    
    async def start(self):
        """Запуск планировщика задач"""
        self.running = True
        logger.info("Планировщик задач запущен")
        
        # Запускаем все задачи
        self.tasks = [
            asyncio.create_task(self.cleanup_duplicates_task()),
            asyncio.create_task(self.cleanup_old_stats_task()),
            asyncio.create_task(self.update_chat_info_task()),
            asyncio.create_task(self.mute_expiry_task()),  # Новая задача для проверки истечения мутов
            asyncio.create_task(self.ban_expiry_task()),  # Новая задача для проверки истечения банов
            asyncio.create_task(self.cleanup_old_moderation_records_task()),  # Очистка старых записей модерации
            asyncio.create_task(self.reputation_recovery_task()),  # Восстановление репутации
            asyncio.create_task(self.cleanup_old_punishments_task()),  # Очистка старых наказаний
            asyncio.create_task(self.cleanup_expired_network_codes_task()),  # Очистка истекших кодов сетки
            asyncio.create_task(self.cleanup_expired_votes_task()),  # Очистка истекших голосований
            asyncio.create_task(self.cleanup_raid_protection_task()),  # Очистка старых записей защиты от рейдов
            asyncio.create_task(self.cleanup_inactive_task())  # Очистка неактивных пользователей и чатов
        ]
        
        # Ждем завершения всех задач
        await asyncio.gather(*self.tasks, return_exceptions=True)
    
    async def stop(self):
        """Остановка планировщика задач"""
        self.running = False
        logger.info("Останавливаем планировщик задач...")
        
        # Отменяем все задачи
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # Ждем завершения всех задач
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
                # Даем время на полное завершение
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"Ошибка при остановке задач планировщика: {e}")
        
        logger.info("Планировщик задач остановлен")
    
    async def cleanup_duplicates_task(self):
        """Задача очистки дубликатов чатов каждые 5 минут"""
        while self.running:
            try:
                await db.cleanup_duplicate_chats()
                logger.info("Автоматическая очистка дубликатов выполнена")
            except Exception as e:
                logger.error(f"Ошибка при автоматической очистке дубликатов: {e}")
            
            # Ждем 5 минут
            await asyncio.sleep(300)
    
    async def cleanup_old_stats_task(self):
        """Задача очистки старых записей статистики каждый час"""
        while self.running:
            try:
                await db.cleanup_old_stats(7)
                await db.cleanup_old_user_stats(7)
                logger.info("Автоматическая очистка старых записей выполнена")
            except Exception as e:
                logger.error(f"Ошибка при автоматической очистке старых записей: {e}")
            
            # Ждем 1 час
            await asyncio.sleep(3600)
    
    async def update_chat_info_task(self):
        """Задача обновления информации о чатах каждую минуту"""
        while self.running:
            try:
                # Получаем список ВСЕХ активных чатов (включая приватные)
                chats = await db.get_all_chats_for_update()
                
                # Функция для обработки одного чата с ограничением конкурентности
                async def update_single_chat(chat):
                    async with self.chat_semaphore:
                        try:
                            # Обновляем информацию о чате
                            # Импортируем функцию динамически, чтобы избежать циклического импорта
                            import bot
                            await bot.update_chat_info_if_needed(chat['chat_id'])
                        except Exception as e:
                            error_str = str(e).lower()
                            # Логируем "chat not found" только в DEBUG, функция сама деактивирует чат
                            if "chat not found" in error_str or "bad request" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} не найден при обновлении информации: {e}")
                            else:
                                logger.error(f"Ошибка при обновлении информации о чате {chat['chat_id']}: {e}")
                
                # Обрабатываем все чаты параллельно с ограничением через семафор
                await asyncio.gather(*[update_single_chat(chat) for chat in chats], return_exceptions=True)
                
                logger.info(f"Автоматическое обновление информации о {len(chats)} чатах выполнено")
            except Exception as e:
                logger.error(f"Ошибка при автоматическом обновлении информации о чатах: {e}")
            
            # Ждем 1 минуту
            await asyncio.sleep(60)
    
    async def mute_expiry_task(self):
        """Задача проверки истечения мутов - сканирует каждые 10 сек если есть активные муты"""
        # Множество для отслеживания уже обработанных мутов (ID -> timestamp последней обработки)
        # Используем словарь на уровне класса задачи для отслеживания между итерациями
        if not hasattr(self, '_recently_processed_mutes'):
            self._recently_processed_mutes = {}
        
        while self.running:
            try:
                # Очищаем старые записи (старше 60 секунд)
                current_time = time.time()
                self._recently_processed_mutes = {
                    mute_id: ts for mute_id, ts in self._recently_processed_mutes.items() 
                    if current_time - ts < 60
                }
                
                # Проверяем, есть ли активные муты во всех чатах
                has_active_mutes = False
                total_active_mutes = 0
                
                # Получаем все активные чаты
                chats = await db.get_all_chats_for_update()
                logger.debug(f"Проверяем муты в {len(chats)} чатах")
                
                # Функция для обработки одного чата
                async def process_chat_mutes(chat, recently_processed_ref, current_time_ref):
                    async with self.chat_semaphore:
                        try:
                            # Проверяем права администратора
                            import bot
                            try:
                                bot_member = await bot.bot.get_chat_member(chat['chat_id'], bot.bot.id)
                            except Exception as e:
                                error_str = str(e).lower()
                                # Обрабатываем ошибки "chat not found" - деактивируем чат и пропускаем
                                if "chat not found" in error_str or "chat not found" in error_str or "bad request" in error_str:
                                    logger.info(f"Чат {chat['chat_id']} не найден, деактивируем его")
                                    try:
                                        await db.deactivate_chat(chat['chat_id'])
                                    except Exception:
                                        pass  # Игнорируем ошибки деактивации
                                    return 0
                                raise  # Перебрасываем другие ошибки
                            
                            if bot_member.status not in ['administrator', 'creator']:
                                return 0
                            
                            # Получаем активные муты в этом чате
                            active_mutes = await moderation_db.get_active_punishments(chat['chat_id'], "mute")
                            
                            if not active_mutes:
                                return 0
                            
                            must_active_count = len(active_mutes)
                            logger.debug(f"В чате {chat['chat_id']} найдено {must_active_count} активных мутов")
                            
                            expired_count = 0
                            
                            for mute in active_mutes:
                                try:
                                    mute_id = mute['id']
                                    
                                    # Проверяем, не обрабатывали ли мы этот мут недавно (защита от спама)
                                    if mute_id in recently_processed_ref:
                                        time_since_processed = current_time_ref - recently_processed_ref[mute_id]
                                        if time_since_processed < 30:  # Если обрабатывали менее 30 секунд назад - пропускаем
                                            logger.debug(f"Мут {mute_id} был обработан {time_since_processed:.1f} сек назад, пропускаем")
                                            continue
                                    
                                    # Проверяем, истек ли мут
                                    if mute['expiry_date']:
                                        expiry_date = datetime.fromisoformat(mute['expiry_date'])
                                        # Используем UTC для сравнения
                                        now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo else datetime.now()
                                        
                                        # Логируем для отладки
                                        logger.debug(f"Проверяем мут {mute_id}: expiry={expiry_date}, now={now}, diff={(now - expiry_date).total_seconds()} сек")
                                        
                                        # Проверяем только если мут действительно истек
                                        time_diff = (now - expiry_date).total_seconds()
                                        if time_diff < 0:
                                            continue  # Мут еще не истек
                                        
                                        if time_diff >= 0:
                                            # Сначала атомарно деактивируем наказание, чтобы избежать повторной обработки
                                            deactivated = await moderation_db.deactivate_punishment(mute_id)
                                            
                                            # Проверяем, что деактивация прошла успешно (защита от дублирования)
                                            if not deactivated:
                                                logger.debug(f"Мут {mute_id} уже был обработан другим потоком, пропускаем")
                                                recently_processed_ref[mute_id] = current_time_ref
                                                continue
                                            
                                            # Помечаем как обработанный (даже если дальше будет ошибка, не будем обрабатывать снова)
                                            recently_processed_ref[mute_id] = current_time_ref
                                            
                                            logger.info(f"Мут истек для пользователя {mute['user_id']} в чате {chat['chat_id']}")
                                            
                                            # Мут истек - снимаем ограничения
                                            import bot
                                            try:
                                                await bot.bot.restrict_chat_member(
                                                    chat_id=chat['chat_id'],
                                                    user_id=mute['user_id'],
                                                    permissions=bot.types.ChatPermissions(
                                                        can_send_messages=True,
                                                        can_send_media_messages=True,
                                                        can_send_polls=True,
                                                        can_send_other_messages=True,
                                                        can_add_web_page_previews=True,
                                                        can_change_info=False,
                                                        can_invite_users=False,
                                                        can_pin_messages=False
                                                    )
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                # Обрабатываем ошибки "chat not found" - только логируем в DEBUG
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при снятии ограничений: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при снятии ограничений для пользователя {mute['user_id']}: {e}")
                                            
                                            # Отправляем сообщение о размуте
                                            username_display = mute['user_first_name'] or f"@{mute['user_username']}" if mute['user_username'] else f"ID{mute['user_id']}"
                                            
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
                                            
                                            try:
                                                await bot.bot.send_message(
                                                    chat['chat_id'],
                                                    f"🔊 Участник <b>{username_display}</b> <i>освобожден(а) от тайм-аута</i>\n"
                                                    f"🔸 <b>По истечению времени я автоматически снял ограничения, не нарушайте правила чата!</b>\n\n"
                                                    f"<blockquote>{quote}</blockquote>",
                                                    parse_mode=bot.ParseMode.HTML
                                                )
                                                logger.info(f"✅ Автоматически снят мут пользователю {mute['user_id']} в чате {chat['chat_id']}")
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                # Обрабатываем ошибки "chat not found" - только логируем в DEBUG
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при отправке сообщения о размуте: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при отправке сообщения о размуте: {e}")
                                            
                                            expired_count += 1
                                            
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке мута {mute['id']}: {e}")
                                    continue
                            
                            return must_active_count
                                
                        except Exception as e:
                            error_str = str(e).lower()
                            # Логируем "chat not found" только в DEBUG, иначе деактивируем и пропускаем
                            if "chat not found" in error_str or "bad request" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} не найден при проверке мутов: {e}")
                                try:
                                    await db.deactivate_chat(chat['chat_id'])
                                except Exception:
                                    pass
                            else:
                                logger.error(f"Ошибка при проверке мутов в чате {chat['chat_id']}: {e}")
                            return 0
                
                # Обрабатываем все чаты параллельно
                results = await asyncio.gather(*[process_chat_mutes(chat, self._recently_processed_mutes, current_time) for chat in chats], return_exceptions=True)
                
                # Подсчитываем результаты
                for result in results:
                    if isinstance(result, int):
                        if result > 0:
                            total_active_mutes += result
                            has_active_mutes = True
                
                # Если есть активные муты - ждем 10 секунд, иначе 60 секунд
                if has_active_mutes:
                    logger.info(f"Найдено {total_active_mutes} активных мутов - сканируем через 10 секунд")
                    await asyncio.sleep(10)
                else:
                    logger.debug("Нет активных мутов - сканируем через 60 секунд")
                    await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки мутов: {e}")
                # При ошибке ждем 30 секунд
                await asyncio.sleep(30)
    
    async def ban_expiry_task(self):
        """Задача для автоматического разбана истекших банов"""
        logger.info("Запущена задача проверки истечения банов")
        
        while self.running:
            try:
                # Получаем все чаты
                chats = await db.get_all_chats_for_update()
                total_active_bans = 0
                has_active_bans = False
                
                # Функция для обработки одного чата
                async def process_chat_bans(chat):
                    async with self.chat_semaphore:
                        try:
                            # Получаем активные баны для этого чата
                            active_bans = await moderation_db.get_active_punishments(chat['chat_id'], "ban")
                            
                            if not active_bans:
                                return 0
                            
                            ban_count = len(active_bans)
                            
                            # Проверяем каждый бан на истечение
                            for ban in active_bans:
                                try:
                                    # Проверяем, истек ли бан
                                    if ban['expiry_date']:
                                        expiry_date = datetime.fromisoformat(ban['expiry_date'])
                                        # Используем UTC для сравнения
                                        now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo else datetime.now()
                                        if now >= expiry_date:
                                            # Сначала атомарно деактивируем наказание, чтобы избежать повторной обработки
                                            deactivated = await moderation_db.deactivate_punishment(ban['id'])
                                            
                                            # Проверяем, что деактивация прошла успешно (защита от дублирования)
                                            if not deactivated:
                                                logger.warning(f"Бан {ban['id']} уже был обработан другим потоком, пропускаем")
                                                continue
                                            
                                            logger.info(f"Бан истек для пользователя {ban['user_id']} в чате {chat['chat_id']}")
                                            
                                            # Разбаниваем пользователя
                                            import bot
                                            try:
                                                await bot.bot.unban_chat_member(
                                                    chat_id=chat['chat_id'],
                                                    user_id=ban['user_id']
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                # Обрабатываем ошибки "chat not found" - только логируем в DEBUG
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при разбане: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при разбане пользователя {ban['user_id']}: {e}")
                                            
                                            # Формируем имя пользователя
                                            username_display = ban['user_first_name'] or f"@{ban['user_username']}" if ban['user_username'] else f"ID{ban['user_id']}"
                                            
                                            # Философские цитаты для автоматического разбана
                                            philosophical_quotes = [
                                                "🌅 Время лечит все раны, даже самые глубокие",
                                                "🌊 Река находит путь к морю, преодолевая все препятствия",
                                                "🕊️ Птица свободы всегда найдет путь домой",
                                                "🌱 Из пепла может вырасти новая жизнь",
                                                "🌙 Даже самая темная ночь заканчивается рассветом",
                                                "🍃 Новый лист может вырасти на том же дереве",
                                                "🌌 Звезды не исчезают навсегда, они просто ждут своего времени",
                                                "🌿 Дерево может зацвести заново после зимы",
                                                "🦋 Превращение требует времени, но результат стоит ожидания",
                                                "🌅 Солнце всегда возвращается, даже после самой долгой ночи"
                                            ]
                                            
                                            import random
                                            quote = random.choice(philosophical_quotes)
                                            
                                            # Отправляем сообщение в чат
                                            try:
                                                await bot.bot.send_message(
                                                    chat['chat_id'],
                                                    f"✅ <b>{username_display}</b> <i>был(а) автоматически разбанен(а)</i>\n"
                                                    f"🔸 <b>Срок наказания истек</b>\n\n"
                                                    f"<blockquote>{quote}</blockquote>",
                                                    parse_mode=bot.ParseMode.HTML
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                # Обрабатываем ошибки "chat not found" - только логируем в DEBUG
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при отправке сообщения о разбане: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при отправке сообщения о разбане: {e}")
                                            
                                            # Отправляем уведомление в ЛС пользователю
                                            try:
                                                try:
                                                    chat_info = await bot.bot.get_chat(chat['chat_id'])
                                                    chat_title = chat_info.title or "Неизвестный чат"
                                                except Exception as e:
                                                    error_str = str(e).lower()
                                                    # Если чат не найден, используем дефолтное название
                                                    if "chat not found" in error_str or "bad request" in error_str:
                                                        if DEBUG:
                                                            logger.debug(f"Чат {chat['chat_id']} не найден при получении информации: {e}")
                                                        chat_title = "неизвестный чат"
                                                    else:
                                                        raise
                                                
                                                # Создаем кнопку "Открыть чат"
                                                from aiogram.utils.keyboard import InlineKeyboardBuilder
                                                builder = InlineKeyboardBuilder()
                                                try:
                                                    builder.button(text="💬 Открыть чат", url=f"https://t.me/{chat_info.username}" if chat_info.username else f"https://t.me/c/{str(chat['chat_id'])[4:]}")
                                                except:
                                                    pass  # Если chat_info не определен
                                                
                                                await bot.bot.send_message(
                                                    ban['user_id'],
                                                    f"✅ Вы были автоматически разбанены в чате \"{chat_title}\"\n"
                                                    f"🔸 Срок наказания истек\n\n"
                                                    f"<blockquote>{quote}</blockquote>",
                                                    parse_mode=bot.ParseMode.HTML,
                                                    reply_markup=builder.as_markup() if builder else None
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                # Обрабатываем ошибки "chat not found" - только логируем в DEBUG
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при отправке уведомления: {e}")
                                                else:
                                                    logger.error(f"Ошибка при отправке уведомления пользователю {ban['user_id']}: {e}")
                                            
                                            logger.info(f"✅ Автоматически разбанен пользователь {ban['user_id']} в чате {chat['chat_id']}")
                                            
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке бана {ban['id']}: {e}")
                            
                            return ban_count
                                    
                        except Exception as e:
                            error_str = str(e).lower()
                            # Логируем "chat not found" только в DEBUG, иначе деактивируем и пропускаем
                            if "chat not found" in error_str or "bad request" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} не найден при проверке банов: {e}")
                                try:
                                    await db.deactivate_chat(chat['chat_id'])
                                except Exception:
                                    pass
                            else:
                                logger.error(f"Ошибка при проверке банов в чате {chat['chat_id']}: {e}")
                            return 0
                
                # Обрабатываем все чаты параллельно
                results = await asyncio.gather(*[process_chat_bans(chat) for chat in chats], return_exceptions=True)
                
                # Подсчитываем результаты
                for result in results:
                    if isinstance(result, int):
                        if result > 0:
                            total_active_bans += result
                            has_active_bans = True
                
                # Если есть активные баны - ждем 10 секунд, иначе 60 секунд
                if has_active_bans:
                    logger.info(f"Найдено {total_active_bans} активных банов - сканируем через 10 секунд")
                    await asyncio.sleep(10)
                else:
                    logger.debug("Нет активных банов - сканируем через 60 секунд")
                    await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки банов: {e}")
                # При ошибке ждем 30 секунд
                await asyncio.sleep(30)
    
    async def cleanup_old_moderation_records_task(self):
        """Задача очистки старых записей модерации"""
        logger.info("Задача автоматической очистки старых записей модерации запущена")
        
        # Ждем 1 час после запуска бота, чтобы не мешать работе
        await asyncio.sleep(3600)
        
        while self.running:
            try:
                # Очищаем старые записи (старше 6 месяцев)
                success = await moderation_db.cleanup_old_records(days_to_keep=180)
                if success:
                    logger.info("Автоматическая очистка старых записей модерации завершена")
                else:
                    logger.warning("Ошибка при автоматической очистке старых записей модерации")
                
                # Выполняем очистку раз в неделю (604800 секунд = 7 дней)
                await asyncio.sleep(604800)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче автоматической очистки старых записей модерации: {e}")
                # При ошибке ждем 6 часов
                await asyncio.sleep(21600)
    
    async def reputation_recovery_task(self):
        """Задача восстановления репутации: +1 каждые 4 часа, +2 по выходным (МСК)"""
        logger.info("Задача восстановления репутации запущена")
        
        # Ждем 2 часа после запуска бота
        await asyncio.sleep(7200)
        
        while self.running:
            try:
                # Определяем московскую дату/день недели
                ts = datetime.utcnow().timestamp() + 10800
                moscow_dt = datetime.utcfromtimestamp(ts)
                weekday = moscow_dt.isoweekday()  # 1=Mon ... 7=Sun
                delta = 2 if weekday in (6, 7) else 1
                
                # Получаем всех пользователей с репутацией < 100
                users = await reputation_db.get_all_users_with_reputation()
                
                if users:
                    logger.info(f"Проверяем восстановление репутации для {len(users)} пользователей; прирост={delta}")
                    
                    recovered_count = 0
                    for user in users:
                        user_id = user['user_id']
                        
                        # Проверяем наказания за последние 24 часа
                        recent_punishments = await reputation_db.get_recent_punishments(user_id, days=1)
                        
                        # Если нет нарушений за последние 24 часа, восстанавливаем
                        if not recent_punishments:
                            await reputation_db.update_reputation(user_id, delta)
                            recovered_count += 1
                    
                    if recovered_count > 0:
                        logger.info(f"Восстановлена репутация для {recovered_count} пользователей")
                else:
                    logger.debug("Нет пользователей для восстановления репутации")
                
                # Выполняем восстановление каждые 4 часа
                await asyncio.sleep(14400)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче восстановления репутации: {e}")
                # При ошибке ждем 1 час
                await asyncio.sleep(3600)
    
    async def cleanup_old_punishments_task(self):
        """Задача очистки старых наказаний из базы репутации"""
        logger.info("Задача очистки старых наказаний репутации запущена")
        
        # Ждем 3 часа после запуска бота
        await asyncio.sleep(10800)
        
        while self.running:
            try:
                # Очищаем наказания старше 3 дней
                deleted_count = await reputation_db.cleanup_old_punishments(days=3)
                
                if deleted_count > 0:
                    logger.info(f"Очищено {deleted_count} старых наказаний из базы репутации")
                else:
                    logger.debug("Нет старых наказаний для очистки")
                
                # Выполняем очистку раз в день
                await asyncio.sleep(86400)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки старых наказаний репутации: {e}")
                # При ошибке ждем 6 часов
                await asyncio.sleep(21600)
    
    async def cleanup_expired_network_codes_task(self):
        """Задача очистки истекших кодов сетки чатов"""
        logger.info("Задача очистки истекших кодов сетки запущена")
        
        # Ждем 30 минут после запуска бота
        await asyncio.sleep(1800)
        
        while self.running:
            try:
                # Очищаем истекшие коды
                deleted_count = await network_db.cleanup_expired_codes()
                
                if deleted_count > 0:
                    logger.info(f"Очищено {deleted_count} истекших кодов сетки")
                else:
                    logger.debug("Нет истекших кодов для очистки")
                
                # Выполняем очистку каждые 5 минут
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки истекших кодов сетки: {e}")
                # При ошибке ждем 5 минут
                await asyncio.sleep(300)
    
    async def cleanup_expired_votes_task(self):
        """Задача очистки истекших голосований за мут"""
        logger.info("Задача очистки истекших голосований запущена")
        
        # Ждем 1 минуту после запуска бота
        await asyncio.sleep(60)
        
        while self.running:
            try:
                # Импортируем votemute_db здесь, чтобы избежать циклического импорта
                from votemute_db import votemute_db
                
                # Очищаем истекшие голосования
                deleted_count = await votemute_db.cleanup_expired_votes()
                
                if deleted_count > 0:
                    logger.info(f"Очищено {deleted_count} истекших голосований")
                else:
                    logger.debug("Нет истекших голосований для очистки")
                
                # Выполняем очистку каждые 5 минут
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки истекших голосований: {e}")
                # При ошибке ждем 5 минут
                await asyncio.sleep(300)
    
    async def cleanup_raid_protection_task(self):
        """Задача очистки старых записей защиты от рейдов"""
        logger.info("Задача очистки записей защиты от рейдов запущена")
        
        # Ждем 5 минут после запуска бота
        await asyncio.sleep(300)
        
        while self.running:
            try:
                # Импортируем через lazy loader
                raid_db = get_raid_protection_db()
                
                # Очищаем старые записи активности
                await raid_db.cleanup_old_activity(1)
                await raid_db.cleanup_old_joins(2)
                await raid_db.cleanup_old_deleted_messages(5)
                
                logger.debug("Очистка записей защиты от рейдов завершена")
                
                # Выполняем очистку каждые 5 минут
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки записей защиты от рейдов: {e}")
                # При ошибке ждем 5 минут
                await asyncio.sleep(300)
    
    async def cleanup_inactive_task(self):
        """Периодическая очистка неактивных пользователей и чатов"""
        logger.info("🔄 Задача очистки неактивных пользователей и чатов запущена")
        
        # Ждем 24 часа после запуска бота, чтобы не мешать работе
        await asyncio.sleep(86400)
        
        while self.running:
            try:
                logger.info("🧹 Начинаю автоматическую очистку неактивных пользователей и чатов (неактивность > 30 дней)...")
                
                # Очищаем неактивных пользователей и чаты (неактивность > 30 дней)
                stats = await db.cleanup_inactive_users_and_chats(days=30)
                
                logger.info(
                    f"✅ Очистка неактивных завершена: "
                    f"пользователей удалено: {stats['users_deleted']}, "
                    f"чатов удалено: {stats['chats_deleted']}, "
                    f"ошибок пользователей: {stats['users_failed']}, "
                    f"ошибок чатов: {stats['chats_failed']}"
                )
                
                # Выполняем очистку раз в неделю (604800 секунд = 7 дней)
                logger.info("⏰ Следующая очистка неактивных пользователей и чатов через 7 дней")
                await asyncio.sleep(604800)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в задаче очистки неактивных пользователей и чатов: {e}")
                # При ошибке ждем 6 часов
                await asyncio.sleep(21600)


# Глобальный экземпляр планировщика (будет инициализирован в bot.py)
scheduler = None
