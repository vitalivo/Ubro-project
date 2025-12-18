"""
Chat Service
Сервис для работы с чатом в рамках заказа.
Модерация, хранение истории, валидация доступа.
"""

import re
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.chat_message import ChatMessage
from app.models.ride import Ride
from app.schemas.chat_message import ChatMessageSchema, ChatMessageCreate

logger = logging.getLogger(__name__)


# Список запрещённых слов (базовый фильтр мата)
BANNED_WORDS = {
    # Русский мат (базовый список, можно расширить)
    "хуй", "хуя", "хуе", "хуи", "пизд", "блять", "блядь", "бля", "ебать", 
    "ебан", "ебал", "ебу", "еби", "сука", "сучк", "мудак", "мудил",
    "пидор", "пидар", "гандон", "залупа", "шлюх", "дрочи",
    # Английский
    "fuck", "shit", "bitch", "asshole", "dick", "pussy", "cunt",
}

# Регулярное выражение для поиска мата с учётом замены букв на цифры/символы
LEET_REPLACEMENTS = {
    '0': 'о', '1': 'и', '3': 'е', '4': 'а', '5': 's', '6': 'б', '@': 'а',
    '$': 's', '!': 'и', '*': '', '.': '', '-': '', '_': '',
}


class MessageType:
    """Типы сообщений"""
    TEXT = "text"
    IMAGE = "image"
    LOCATION = "location"
    SYSTEM = "system"  # Системные уведомления
    VOICE = "voice"


class ModerationResult:
    """Результат модерации"""
    def __init__(self, passed: bool, original: str, filtered: str, reason: Optional[str] = None):
        self.passed = passed
        self.original = original
        self.filtered = filtered
        self.reason = reason


class ChatService:
    """
    Сервис чата с модерацией и rate limiting.
    
    Функции:
    - Модерация текста (фильтр мата)
    - Rate limiting (защита от спама)
    - Валидация доступа к чату
    - Сохранение/получение истории
    """
    
    def __init__(self):
        # Rate limiting: user_id -> list of timestamps
        self._message_timestamps: Dict[int, List[datetime]] = defaultdict(list)
        # Настройки rate limit
        self.rate_limit_messages = 10  # сообщений
        self.rate_limit_period = 60  # секунд
        # Ограничения
        self.max_message_length = 2000
        self.min_message_length = 1
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста для проверки мата"""
        result = text.lower()
        for leet, normal in LEET_REPLACEMENTS.items():
            result = result.replace(leet, normal)
        return result
    
    def _contains_banned_words(self, text: str) -> tuple[bool, Optional[str]]:
        """Проверка на наличие запрещённых слов"""
        normalized = self._normalize_text(text)
        
        for word in BANNED_WORDS:
            if word in normalized:
                return True, word
        
        return False, None
    
    def _censor_text(self, text: str) -> str:
        """Замена мата на звёздочки"""
        result = text
        normalized = self._normalize_text(text)
        
        for word in BANNED_WORDS:
            if word in normalized:
                # Находим позицию в оригинальном тексте (примерно)
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                result = pattern.sub('*' * len(word), result)
        
        return result
    
    def moderate_message(self, text: str) -> ModerationResult:
        """
        Модерация сообщения.
        
        Returns:
            ModerationResult с флагом passed и отфильтрованным текстом
        """
        if not text:
            return ModerationResult(False, "", "", "Empty message")
        
        # Проверка длины
        if len(text) > self.max_message_length:
            return ModerationResult(
                False, text, text[:self.max_message_length], 
                f"Message too long (max {self.max_message_length})"
            )
        
        if len(text.strip()) < self.min_message_length:
            return ModerationResult(False, text, "", "Message too short")
        
        # Проверка на мат
        has_banned, found_word = self._contains_banned_words(text)
        
        if has_banned:
            censored = self._censor_text(text)
            return ModerationResult(True, text, censored, f"Censored: {found_word}")
        
        return ModerationResult(True, text, text, None)
    
    def check_rate_limit(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Проверка rate limit для пользователя.
        
        Returns:
            (allowed, error_message)
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.rate_limit_period)
        
        # Очищаем старые timestamps
        self._message_timestamps[user_id] = [
            ts for ts in self._message_timestamps[user_id] 
            if ts > cutoff
        ]
        
        if len(self._message_timestamps[user_id]) >= self.rate_limit_messages:
            return False, f"Rate limit exceeded. Max {self.rate_limit_messages} messages per {self.rate_limit_period}s"
        
        # Добавляем текущий timestamp
        self._message_timestamps[user_id].append(now)
        return True, None
    
    async def validate_chat_access(
        self, 
        session: AsyncSession, 
        ride_id: int, 
        user_id: int
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Проверка доступа пользователя к чату заказа.
        
        Returns:
            (allowed, error_message, role)
            role: 'client', 'driver', 'operator'
        """
        query = select(Ride).where(Ride.id == ride_id)
        result = await session.execute(query)
        ride = result.scalar_one_or_none()
        
        if not ride:
            return False, "Ride not found", None
        
        # Проверяем роль
        if ride.client_id == user_id:
            return True, None, "client"
        
        if ride.driver_profile_id:
            # Нужно проверить user_id водителя через driver_profile
            # Пока упрощённо — считаем что driver_profile_id связан с user
            # TODO: связать через driver_profile.user_id
            pass
        
        # TODO: Проверка на оператора (по роли пользователя)
        # Пока разрешаем для тестирования
        return True, None, "operator"
    
    async def save_message(
        self,
        session: AsyncSession,
        ride_id: int,
        sender_id: int,
        text: str,
        message_type: str = MessageType.TEXT,
        receiver_id: Optional[int] = None,
        attachments: Optional[Dict[str, Any]] = None,
        is_moderated: bool = True,
    ) -> ChatMessageSchema:
        """
        Сохранение сообщения в БД.
        """
        message = ChatMessage(
            ride_id=ride_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            text=text,
            message_type=message_type,
            attachments=attachments,
            is_moderated=is_moderated,
            created_at=datetime.utcnow(),
        )
        
        session.add(message)
        await session.flush()
        await session.refresh(message)
        
        return ChatMessageSchema.model_validate(message)
    
    async def get_chat_history(
        self,
        session: AsyncSession,
        ride_id: int,
        limit: int = 50,
        before_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> List[ChatMessageSchema]:
        """
        Получение истории чата для заказа.
        
        Args:
            ride_id: ID заказа
            limit: Количество сообщений
            before_id: Для пагинации — получить сообщения до этого ID
            include_deleted: Включать удалённые сообщения
        """
        conditions = [ChatMessage.ride_id == ride_id]
        
        if before_id:
            conditions.append(ChatMessage.id < before_id)
        
        if not include_deleted:
            conditions.append(ChatMessage.deleted_at.is_(None))
        
        query = (
            select(ChatMessage)
            .where(and_(*conditions))
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        
        result = await session.execute(query)
        messages = result.scalars().all()
        
        # Возвращаем в хронологическом порядке
        return [ChatMessageSchema.model_validate(m) for m in reversed(messages)]
    
    async def soft_delete_message(
        self,
        session: AsyncSession,
        message_id: int,
        user_id: int,
    ) -> bool:
        """
        Мягкое удаление сообщения.
        Только автор может удалить своё сообщение.
        """
        query = select(ChatMessage).where(
            and_(
                ChatMessage.id == message_id,
                ChatMessage.sender_id == user_id,
                ChatMessage.deleted_at.is_(None)
            )
        )
        
        result = await session.execute(query)
        message = result.scalar_one_or_none()
        
        if not message:
            return False
        
        message.deleted_at = datetime.utcnow()
        await session.flush()
        return True
    
    async def edit_message(
        self,
        session: AsyncSession,
        message_id: int,
        user_id: int,
        new_text: str,
    ) -> Optional[ChatMessageSchema]:
        """
        Редактирование сообщения.
        Только автор может редактировать.
        """
        query = select(ChatMessage).where(
            and_(
                ChatMessage.id == message_id,
                ChatMessage.sender_id == user_id,
                ChatMessage.deleted_at.is_(None)
            )
        )
        
        result = await session.execute(query)
        message = result.scalar_one_or_none()
        
        if not message:
            return None
        
        # Модерация нового текста
        moderation = self.moderate_message(new_text)
        
        message.text = moderation.filtered
        message.edited_at = datetime.utcnow()
        message.is_moderated = moderation.passed
        
        await session.flush()
        await session.refresh(message)
        
        return ChatMessageSchema.model_validate(message)
    
    def get_stats(self) -> Dict[str, Any]:
        """Статистика сервиса чата"""
        return {
            "active_users_with_rate_limit": len(self._message_timestamps),
            "rate_limit_config": {
                "messages": self.rate_limit_messages,
                "period_seconds": self.rate_limit_period,
            },
            "max_message_length": self.max_message_length,
        }


# Singleton instance
chat_service = ChatService()
