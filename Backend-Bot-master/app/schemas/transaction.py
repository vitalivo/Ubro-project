from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class TransactionCreate(BaseModel):
    user_id: int
    is_withdraw: bool
    amount: float


class TransactionUpdate(BaseModel):
    user_id: Optional[int] = None
    is_withdraw: Optional[bool] = None
    amount: Optional[float] = None


class TransactionSchema(BaseModel):
    id: int
    user_id: int
    is_withdraw: bool
    amount: float
    created_at: datetime | None = None

    class Config:
        from_attributes = True
