from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, Date, Boolean, ForeignKey, Numeric, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    roll_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    room_number: Mapped[str] = mapped_column(String(30), default="")
    rfid_uid: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))

class Meal(Base):
    __tablename__ = "meals"
    id: Mapped[int] = mapped_column(primary_key=True)
    meal_date: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(20), index=True)  # breakfast/lunch/dinner
    menu: Mapped[str] = mapped_column(String(500), default="")
    reservation_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("meal_date", "meal_type", name="uq_meal_date_type"),)

class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id"))
    status: Mapped[str] = mapped_column(String(20), default="reserved") # reserved/cancelled/no_show
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    student = relationship("Student")
    meal = relationship("Meal")
    __table_args__ = (UniqueConstraint("student_id", "meal_id", name="uq_reservation"),)

class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id"))
    device_id: Mapped[str] = mapped_column(String(100), default="unknown")
    staff_id: Mapped[str] = mapped_column(String(100), default="staff")
    tapped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    served_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="tapped") # tapped/served/rejected
    charge: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    student = relationship("Student")
    meal = relationship("Meal")
    __table_args__ = (UniqueConstraint("student_id", "meal_id", name="uq_collection"),)

class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2)) # positive charge, negative credit/payment
    txn_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
