"""
Модуль для работы с системой друзей
"""
import sqlite3
import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


class FriendsDatabase:
    """Класс для работы с базой данных друзей"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц для друзей"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица для временных кодов добавления в друзья
                db.execute("""
                    CREATE TABLE IF NOT EXISTS friend_codes (
                        user_id INTEGER,
                        code TEXT,
                        expires_at TEXT,
                        created_at TEXT,
                        PRIMARY KEY (user_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                """)
                
                # Таблица для связей друзей
                db.execute("""
                    CREATE TABLE IF NOT EXISTS friendships (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id_1 INTEGER,
                        user_id_2 INTEGER,
                        created_at TEXT,
                        FOREIGN KEY (user_id_1) REFERENCES users (user_id),
                        FOREIGN KEY (user_id_2) REFERENCES users (user_id),
                        UNIQUE(user_id_1, user_id_2)
                    )
                """)
                
                # Создаем индексы для быстрого поиска
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_friendships_user1 
                    ON friendships (user_id_1)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_friendships_user2 
                    ON friendships (user_id_2)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_friend_codes_expires 
                    ON friend_codes (expires_at)
                """)
                
                db.commit()
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
        logger.info("База данных друзей инициализирована")
    
    async def generate_friend_code(self, user_id: int) -> str:
        """Генерирует 6-значный цифровой код для добавления в друзья"""
        def _generate_sync():
            with sqlite3.connect(self.db_path) as db:
                # Сначала очищаем все истекшие коды
                now = datetime.now().isoformat()
                db.execute("DELETE FROM friend_codes WHERE expires_at < ?", (now,))
                
                # Удаляем старые коды пользователя
                db.execute("DELETE FROM friend_codes WHERE user_id = ?", (user_id,))
                
                # Генерируем новый 6-значный цифровой код
                code = ''.join(random.choices(string.digits, k=6))
                expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
                created_at = datetime.now().isoformat()
                
                # Сохраняем код
                db.execute("""
                    INSERT INTO friend_codes (user_id, code, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                """, (user_id, code, expires_at, created_at))
                
                db.commit()
                return code
        
        return await asyncio.get_event_loop().run_in_executor(None, _generate_sync)
    
    async def validate_code(self, code: str, user_id: int) -> tuple[bool, str]:
        """
        Проверяет код и возвращает (is_valid, message)
        """
        def _validate_sync():
            with sqlite3.connect(self.db_path) as db:
                # Ищем код
                cursor = db.execute("""
                    SELECT user_id, expires_at FROM friend_codes 
                    WHERE code = ?
                """, (code,))
                row = cursor.fetchone()
                
                if not row:
                    return False, "❌ Код не найден"
                
                creator_id, expires_at_str = row
                
                # Проверяем срок действия
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.now() > expires_at:
                        return False, "❌ Код истек"
                except ValueError:
                    return False, "❌ Неверный формат кода"
                
                # Проверяем, что не добавляет сам себя
                if creator_id == user_id:
                    return False, "❌ Нельзя добавить себя в друзья"
                
                # Проверяем, что уже не друзья
                def _check_friends_sync():
                    with sqlite3.connect(self.db_path) as db:
                        cursor = db.execute("""
                            SELECT 1 FROM friendships 
                            WHERE (user_id_1 = ? AND user_id_2 = ?) 
                            OR (user_id_1 = ? AND user_id_2 = ?)
                        """, (creator_id, user_id, user_id, creator_id))
                        return cursor.fetchone() is not None
                
                # Проверяем дружбу синхронно
                if _check_friends_sync():
                    return False, "❌ Вы уже друзья"
                
                return True, f"✅ Код действителен! Добавляем в друзья пользователя {creator_id}"
        
        return await asyncio.get_event_loop().run_in_executor(None, _validate_sync)
    
    async def are_friends(self, user_id_1: int, user_id_2: int) -> bool:
        """Проверяет, являются ли пользователи друзьями"""
        def _check_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT 1 FROM friendships 
                    WHERE (user_id_1 = ? AND user_id_2 = ?) 
                    OR (user_id_1 = ? AND user_id_2 = ?)
                """, (user_id_1, user_id_2, user_id_2, user_id_1))
                return cursor.fetchone() is not None
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_sync)
    
    async def add_friendship(self, user_id_1: int, user_id_2: int) -> bool:
        """Добавляет дружбу между пользователями"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Упорядочиваем ID для консистентности
                    smaller_id = min(user_id_1, user_id_2)
                    larger_id = max(user_id_1, user_id_2)
                    
                    db.execute("""
                        INSERT INTO friendships (user_id_1, user_id_2, created_at)
                        VALUES (?, ?, ?)
                    """, (smaller_id, larger_id, datetime.now().isoformat()))
                    
                    # Удаляем использованный код
                    db.execute("DELETE FROM friend_codes WHERE user_id = ?", (user_id_1,))
                    
                    db.commit()
                    return True
            except sqlite3.IntegrityError:
                # Уже друзья
                return False
            except Exception as e:
                logger.error(f"Ошибка при добавлении дружбы: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def remove_friendship(self, user_id_1: int, user_id_2: int) -> bool:
        """Удаляет дружбу между пользователями"""
        def _remove_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    DELETE FROM friendships 
                    WHERE (user_id_1 = ? AND user_id_2 = ?) 
                    OR (user_id_1 = ? AND user_id_2 = ?)
                """, (user_id_1, user_id_2, user_id_2, user_id_1))
                
                db.commit()
                return cursor.rowcount > 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_sync)
    
    async def get_friends(self, user_id: int) -> List[Dict[str, Any]]:
        """Получает список друзей пользователя"""
        def _get_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT 
                        CASE 
                            WHEN f.user_id_1 = ? THEN f.user_id_2 
                            ELSE f.user_id_1 
                        END as friend_id,
                        f.created_at
                    FROM friendships f
                    WHERE f.user_id_1 = ? OR f.user_id_2 = ?
                    ORDER BY f.created_at DESC
                """, (user_id, user_id, user_id))
                
                friends = []
                for row in cursor.fetchall():
                    friend_id, created_at = row
                    friends.append({
                        'user_id': friend_id,
                        'created_at': created_at
                    })
                
                return friends
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def get_friend_count(self, user_id: int) -> int:
        """Получает количество друзей пользователя"""
        def _count_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT COUNT(*) FROM friendships 
                    WHERE user_id_1 = ? OR user_id_2 = ?
                """, (user_id, user_id))
                return cursor.fetchone()[0]
        
        return await asyncio.get_event_loop().run_in_executor(None, _count_sync)
    
    async def cleanup_expired_codes(self):
        """Очищает истекшие коды"""
        def _cleanup_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now().isoformat()
                cursor = db.execute("""
                    DELETE FROM friend_codes WHERE expires_at < ?
                """, (now,))
                deleted_count = cursor.rowcount
                db.commit()
                return deleted_count
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def get_active_codes(self) -> List[Dict[str, Any]]:
        """Получает все активные коды с информацией о пользователях"""
        def _get_active_codes_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now().isoformat()
                cursor = db.execute("""
                    SELECT 
                        fc.user_id,
                        fc.code,
                        fc.expires_at,
                        fc.created_at,
                        u.first_name,
                        u.last_name,
                        u.username
                    FROM friend_codes fc
                    LEFT JOIN users u ON fc.user_id = u.user_id
                    WHERE fc.expires_at > ?
                    ORDER BY fc.created_at DESC
                """, (now,))
                
                codes = []
                for row in cursor.fetchall():
                    user_id, code, expires_at, created_at, first_name, last_name, username = row
                    
                    # Формируем имя пользователя
                    name = first_name or ""
                    if last_name:
                        name += f" {last_name}"
                    name = name.strip() or f"ID{user_id}"
                    
                    codes.append({
                        'user_id': user_id,
                        'code': code,
                        'expires_at': expires_at,
                        'created_at': created_at,
                        'user_name': name,
                        'username': username
                    })
                
                return codes
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_active_codes_sync)
    
    async def get_user_active_codes(self, user_id: int) -> List[Dict[str, Any]]:
        """Получает активные коды конкретного пользователя"""
        def _get_user_codes_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now().isoformat()
                cursor = db.execute("""
                    SELECT code, expires_at, created_at
                    FROM friend_codes 
                    WHERE user_id = ? AND expires_at > ?
                    ORDER BY created_at DESC
                """, (user_id, now))
                
                codes = []
                for row in cursor.fetchall():
                    code, expires_at, created_at = row
                    codes.append({
                        'code': code,
                        'expires_at': expires_at,
                        'created_at': created_at
                    })
                
                return codes
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_codes_sync)
    
    async def delete_user_friends(self, user_id: int) -> bool:
        """Удалить все данные пользователя из системы друзей"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем из friend_codes (коды пользователя)
                    db.execute("DELETE FROM friend_codes WHERE user_id = ?", (user_id,))
                    
                    # Удаляем из friendships (все связи где user_id_1 или user_id_2 = user_id)
                    db.execute("""
                        DELETE FROM friendships 
                        WHERE user_id_1 = ? OR user_id_2 = ?
                    """, (user_id, user_id))
                    
                    db.commit()
                    logger.info(f"Данные пользователя {user_id} удалены из системы друзей")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении данных пользователя {user_id} из системы друзей: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)


# Создаем глобальный экземпляр
friends_db = FriendsDatabase()
