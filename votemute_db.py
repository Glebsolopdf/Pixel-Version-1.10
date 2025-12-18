"""
Модуль для работы с базой данных голосований за мут
Отдельная БД для изоляции данных голосований от основной статистики
"""
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Импортируем BASE_PATH из config, если доступен
try:
    from config import BASE_PATH
except ImportError:
    BASE_PATH = Path(__file__).parent.absolute()

class VoteMuteDatabase:
    """Класс для работы с базой данных голосований за мут"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'votemute.db')
        self.db_path = db_path
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица активных голосований
                db.execute("""
                    CREATE TABLE IF NOT EXISTS active_votes (
                        vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        target_user_id INTEGER,
                        creator_id INTEGER,
                        mute_duration INTEGER,
                        required_votes INTEGER,
                        vote_duration INTEGER,
                        created_at TEXT,
                        expires_at TEXT,
                        is_pinned BOOLEAN DEFAULT 0,
                        message_id INTEGER,
                        target_username TEXT,
                        target_first_name TEXT,
                        target_last_name TEXT,
                        creator_username TEXT,
                        creator_first_name TEXT,
                        creator_last_name TEXT
                    )
                """)
                
                # Таблица результатов голосования
                db.execute("""
                    CREATE TABLE IF NOT EXISTS vote_results (
                        vote_id INTEGER,
                        user_id INTEGER,
                        vote_type TEXT,
                        voted_at TEXT,
                        last_change_at TEXT,
                        PRIMARY KEY (vote_id, user_id),
                        FOREIGN KEY (vote_id) REFERENCES active_votes (vote_id)
                    )
                """)
                
                # Таблица кулдаунов на создание голосований
                db.execute("""
                    CREATE TABLE IF NOT EXISTS vote_cooldowns (
                        chat_id INTEGER PRIMARY KEY,
                        last_vote_created_at TEXT
                    )
                """)
                
                # Таблица истории завершенных голосований
                db.execute("""
                    CREATE TABLE IF NOT EXISTS vote_history (
                        vote_id INTEGER,
                        chat_id INTEGER,
                        target_user_id INTEGER,
                        creator_id INTEGER,
                        mute_duration INTEGER,
                        required_votes INTEGER,
                        vote_duration INTEGER,
                        created_at TEXT,
                        finished_at TEXT,
                        result TEXT,
                        reason TEXT,
                        votes_yes INTEGER,
                        votes_no INTEGER,
                        target_username TEXT,
                        target_first_name TEXT,
                        target_last_name TEXT,
                        creator_username TEXT,
                        creator_first_name TEXT,
                        creator_last_name TEXT
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_active_votes_chat ON active_votes (chat_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_active_votes_expires ON active_votes (expires_at)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_vote_results_vote ON vote_results (vote_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_vote_results_user ON vote_results (user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_vote_history_chat ON vote_history (chat_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_vote_history_target ON vote_history (target_user_id)")
                
                db.commit()
                logger.info("База данных голосований за мут инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def create_vote(self, chat_id: int, target_user_id: int, creator_id: int,
                         mute_duration: int, required_votes: int, vote_duration: int,
                         is_pinned: bool = False, message_id: int = None,
                         target_username: str = None, target_first_name: str = None, target_last_name: str = None,
                         creator_username: str = None, creator_first_name: str = None, creator_last_name: str = None) -> int:
        """Создать новое голосование"""
        def _create_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now()
                expires_at = now + timedelta(minutes=vote_duration)
                
                cursor = db.execute("""
                    INSERT INTO active_votes 
                    (chat_id, target_user_id, creator_id, mute_duration, required_votes, vote_duration,
                     created_at, expires_at, is_pinned, message_id, target_username, target_first_name, target_last_name,
                     creator_username, creator_first_name, creator_last_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, target_user_id, creator_id, mute_duration, required_votes, vote_duration,
                      now.isoformat(), expires_at.isoformat(), is_pinned, message_id,
                      target_username, target_first_name, target_last_name,
                      creator_username, creator_first_name, creator_last_name))
                
                vote_id = cursor.lastrowid
                db.commit()
                return vote_id
        
        return await asyncio.get_event_loop().run_in_executor(None, _create_sync)
    
    async def get_active_vote(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получить активное голосование в чате"""
        def _get_sync():
            with sqlite3.connect(self.db_path) as db:
                db.row_factory = sqlite3.Row
                cursor = db.execute("""
                    SELECT * FROM active_votes 
                    WHERE chat_id = ? AND expires_at > ?
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (chat_id, datetime.now().isoformat()))
                
                row = cursor.fetchone()
                return dict(row) if row else None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def get_vote_by_id(self, vote_id: int) -> Optional[Dict[str, Any]]:
        """Получить голосование по ID"""
        def _get_sync():
            with sqlite3.connect(self.db_path) as db:
                db.row_factory = sqlite3.Row
                cursor = db.execute("SELECT * FROM active_votes WHERE vote_id = ?", (vote_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def add_vote(self, vote_id: int, user_id: int, vote_type: str) -> bool:
        """Добавить или изменить голос пользователя"""
        def _add_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now()
                
                # Проверяем, есть ли уже голос от этого пользователя
                cursor = db.execute("""
                    SELECT vote_type, last_change_at FROM vote_results 
                    WHERE vote_id = ? AND user_id = ?
                """, (vote_id, user_id))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Проверяем кулдаун (30 секунд)
                    last_change = datetime.fromisoformat(existing[1])
                    if (now - last_change).total_seconds() < 30:
                        return False
                    
                    # Обновляем существующий голос
                    db.execute("""
                        UPDATE vote_results 
                        SET vote_type = ?, voted_at = ?, last_change_at = ?
                        WHERE vote_id = ? AND user_id = ?
                    """, (vote_type, now.isoformat(), now.isoformat(), vote_id, user_id))
                else:
                    # Добавляем новый голос
                    db.execute("""
                        INSERT INTO vote_results (vote_id, user_id, vote_type, voted_at, last_change_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (vote_id, user_id, vote_type, now.isoformat(), now.isoformat()))
                
                db.commit()
                return True
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def get_vote_results(self, vote_id: int) -> Dict[str, int]:
        """Получить результаты голосования"""
        def _get_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT vote_type, COUNT(*) as count 
                    FROM vote_results 
                    WHERE vote_id = ?
                    GROUP BY vote_type
                """, (vote_id,))
                
                results = {"yes": 0, "no": 0}
                for row in cursor.fetchall():
                    results[row[0]] = row[1]
                
                return results
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def finish_vote(self, vote_id: int, result: str, reason: str) -> Optional[Dict[str, Any]]:
        """Завершить голосование и перенести в историю"""
        def _finish_sync():
            with sqlite3.connect(self.db_path) as db:
                # Получаем данные голосования
                vote_cursor = db.execute("SELECT * FROM active_votes WHERE vote_id = ?", (vote_id,))
                vote_data = vote_cursor.fetchone()
                
                if not vote_data:
                    return None
                
                # Получаем результаты голосования
                results_cursor = db.execute("""
                    SELECT vote_type, COUNT(*) as count 
                    FROM vote_results 
                    WHERE vote_id = ?
                    GROUP BY vote_type
                """, (vote_id,))
                
                results = {"yes": 0, "no": 0}
                for row in results_cursor.fetchall():
                    results[row[0]] = row[1]
                
                # Переносим в историю
                db.execute("""
                    INSERT INTO vote_history 
                    (vote_id, chat_id, target_user_id, creator_id, mute_duration, required_votes, vote_duration,
                     created_at, finished_at, result, reason, votes_yes, votes_no,
                     target_username, target_first_name, target_last_name,
                     creator_username, creator_first_name, creator_last_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (vote_id, vote_data[0], vote_data[1], vote_data[2], vote_data[3], vote_data[4], vote_data[5],
                      vote_data[6], datetime.now().isoformat(), result, reason, results["yes"], results["no"],
                      vote_data[11], vote_data[12], vote_data[13], vote_data[14], vote_data[15], vote_data[16]))
                
                # Удаляем из активных голосований
                db.execute("DELETE FROM active_votes WHERE vote_id = ?", (vote_id,))
                
                # Удаляем результаты голосования
                db.execute("DELETE FROM vote_results WHERE vote_id = ?", (vote_id,))
                
                db.commit()
                return dict(zip([col[0] for col in vote_cursor.description], vote_data))
        
        return await asyncio.get_event_loop().run_in_executor(None, _finish_sync)
    
    async def check_cooldown(self, chat_id: int) -> bool:
        """Проверить кулдаун создания голосований (3 минуты)"""
        def _check_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT last_vote_created_at FROM vote_cooldowns 
                    WHERE chat_id = ?
                """, (chat_id,))
                
                row = cursor.fetchone()
                if not row:
                    return True
                
                last_created = datetime.fromisoformat(row[0])
                return (datetime.now() - last_created).total_seconds() >= 180  # 3 минуты
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_sync)
    
    async def set_cooldown(self, chat_id: int):
        """Установить кулдаун создания голосований"""
        def _set_sync():
            with sqlite3.connect(self.db_path) as db:
                db.execute("""
                    INSERT OR REPLACE INTO vote_cooldowns (chat_id, last_vote_created_at)
                    VALUES (?, ?)
                """, (chat_id, datetime.now().isoformat()))
                db.commit()
        
        await asyncio.get_event_loop().run_in_executor(None, _set_sync)
    
    async def cleanup_expired_votes(self):
        """Очистка истекших голосований"""
        def _cleanup_sync():
            with sqlite3.connect(self.db_path) as db:
                now = datetime.now().isoformat()
                
                # Получаем истекшие голосования
                cursor = db.execute("""
                    SELECT vote_id FROM active_votes 
                    WHERE expires_at <= ?
                """, (now,))
                
                expired_votes = [row[0] for row in cursor.fetchall()]
                
                for vote_id in expired_votes:
                    # Переносим в историю как неудачные
                    vote_cursor = db.execute("SELECT * FROM active_votes WHERE vote_id = ?", (vote_id,))
                    vote_data = vote_cursor.fetchone()
                    
                    if vote_data:
                        # Получаем результаты
                        results_cursor = db.execute("""
                            SELECT vote_type, COUNT(*) as count 
                            FROM vote_results 
                            WHERE vote_id = ?
                            GROUP BY vote_type
                        """, (vote_id,))
                        
                        results = {"yes": 0, "no": 0}
                        for row in results_cursor.fetchall():
                            results[row[0]] = row[1]
                        
                        # Переносим в историю
                        db.execute("""
                            INSERT INTO vote_history 
                            (vote_id, chat_id, target_user_id, creator_id, mute_duration, required_votes, vote_duration,
                             created_at, finished_at, result, reason, votes_yes, votes_no,
                             target_username, target_first_name, target_last_name,
                             creator_username, creator_first_name, creator_last_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (vote_id, vote_data[0], vote_data[1], vote_data[2], vote_data[3], vote_data[4], vote_data[5],
                              vote_data[6], now, "failed", "Время истекло", results["yes"], results["no"],
                              vote_data[11], vote_data[12], vote_data[13], vote_data[14], vote_data[15], vote_data[16]))
                        
                        # Удаляем из активных
                        db.execute("DELETE FROM active_votes WHERE vote_id = ?", (vote_id,))
                        db.execute("DELETE FROM vote_results WHERE vote_id = ?", (vote_id,))
                
                db.commit()
                return len(expired_votes)
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def update_vote_message_id(self, vote_id: int, message_id: int):
        """Обновить message_id голосования"""
        def _update_sync():
            with sqlite3.connect(self.db_path) as db:
                db.execute("""
                    UPDATE active_votes 
                    SET message_id = ? 
                    WHERE vote_id = ?
                """, (message_id, vote_id))
                db.commit()
        
        await asyncio.get_event_loop().run_in_executor(None, _update_sync)

# Глобальный экземпляр базы данных
votemute_db = VoteMuteDatabase()
