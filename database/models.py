from datetime import date, datetime
import enum
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class DutyType(str, enum.Enum):
    DAILY = "DAILY"
    CLEANING = "CLEANING"
    WATER = "WATER"
    LAUNDRY = "LAUNDRY"


class DutyStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SWAPPED = "SWAPPED"
    FINED = "FINED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, doc="Profile ID (1..8)")
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, doc="Telegram User ID")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    room_number: Mapped[int] = mapped_column(Integer, nullable=False, doc="Room number: 1 or 2")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, doc="Position in Round-Robin queue")
    assigned_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, doc="0=Dushanba, ..., 6=Yakshanba, 7=Zaxira")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, doc="Whether user is currently living in apartment")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    duties: Mapped[List["DutyHistory"]] = relationship("DutyHistory", back_populates="user", cascade="all, delete-orphan")
    penalties: Mapped[List["PenaltyFund"]] = relationship("PenaltyFund", back_populates="user", cascade="all, delete-orphan")
    expenses_paid: Mapped[List["Expense"]] = relationship("Expense", back_populates="payer", cascade="all, delete-orphan")
    expense_shares: Mapped[List["ExpenseShare"]] = relationship("ExpenseShare", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, name='{self.full_name}', room={self.room_number}, slot={self.order_index}, active={self.is_active})>"


class DutyHistory(Base):
    __tablename__ = "duty_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    duty_type: Mapped[DutyType] = mapped_column(
        SQLEnum(DutyType, native_enum=False, length=20),
        nullable=False,
        default=DutyType.DAILY,
    )
    duty_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[DutyStatus] = mapped_column(
        SQLEnum(DutyStatus, native_enum=False, length=20),
        nullable=False,
        default=DutyStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="duties")

    def __repr__(self) -> str:
        return f"<DutyHistory(id={self.id}, user_id={self.user_id}, type={self.duty_type}, date={self.duty_date}, status={self.status})>"


class CleaningChecklistState(Base):
    __tablename__ = "cleaning_checklist_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Representative date for the week (e.g. Saturday or Sunday)")
    task_key: Mapped[str] = mapped_column(String(100), nullable=False, doc="Task identifier, e.g., task_pilesos_rooms")
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    completed_by_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[completed_by])

    def __repr__(self) -> str:
        return f"<CleaningChecklistState(week={self.week_date}, task='{self.task_key}', done={self.is_done}, by={self.completed_by})>"


class PenaltyFund(Base):
    __tablename__ = "penalty_fund"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=15000, doc="Penalty amount in UZS")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="penalties")

    def __repr__(self) -> str:
        return f"<PenaltyFund(id={self.id}, user_id={self.user_id}, amount={self.amount}, paid={self.is_paid})>"


class RotationState(Base):
    __tablename__ = "rotation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Reference date for dynamic rotation offset")
    anchor_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=0, doc="Slot index on anchor_date")
    group_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, doc="Active apartment group chat ID")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<RotationState(anchor_date={self.anchor_date}, anchor_slot={self.anchor_slot})>"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, doc="Total amount spent in UZS")
    per_person: Mapped[int] = mapped_column(Integer, nullable=False, doc="Share per active member in UZS")
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    payer: Mapped["User"] = relationship("User", back_populates="expenses_paid")
    shares: Mapped[List["ExpenseShare"]] = relationship("ExpenseShare", back_populates="expense", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Expense(id={self.id}, payer={self.payer_id}, total={self.total_amount}, per_person={self.per_person})>"


class ExpenseShare(Base):
    __tablename__ = "expense_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    expense: Mapped["Expense"] = relationship("Expense", back_populates="shares")
    user: Mapped["User"] = relationship("User", back_populates="expense_shares")

    def __repr__(self) -> str:
        return f"<ExpenseShare(id={self.id}, expense_id={self.expense_id}, user_id={self.user_id}, is_paid={self.is_paid})>"


class DailyTaskState(Base):
    __tablename__ = "daily_task_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    duty_date: Mapped[date] = mapped_column(Date, nullable=False, doc="Date of the daily duty")
    task_key: Mapped[str] = mapped_column(String(50), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationship
    completed_by_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[completed_by])

    def __repr__(self) -> str:
        return f"<DailyTaskState(date={self.duty_date}, task='{self.task_key}', done={self.is_done}, by={self.completed_by})>"


class DutyVote(Base):
    """
    Ovoz berish tizimi (Jarima berilsinmi yoki kechirilsinmi / Falsifikatsiya sudi).
    """
    __tablename__ = "duty_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    duty_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    voter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'FINE' yoki 'FORGIVE'
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # 'INCOMPLETE' yoki 'FRAUD'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    voter: Mapped["User"] = relationship("User", foreign_keys=[voter_id])
    target_user: Mapped["User"] = relationship("User", foreign_keys=[target_user_id])

    def __repr__(self) -> str:
        return f"<DutyVote(date={self.duty_date}, voter={self.voter_id}, target={self.target_user_id}, type={self.vote_type}, reason={self.reason})>"




