from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class StudentCreate(BaseModel):
    name: str
    roll_number: str
    room_number: str = ""
    rfid_uid: str
    phone: str = ""
    photo_url: str = ""

class MealCreate(BaseModel):
    meal_date: date
    meal_type: str
    menu: str = ""
    reservation_deadline: datetime | None = None
    actual_cost: Decimal = Field(default=Decimal("0.00"), ge=0)

class StudentUpdate(BaseModel):
    name: str | None = None
    roll_number: str | None = None
    room_number: str | None = None
    rfid_uid: str | None = None
    phone: str | None = None
    photo_url: str | None = None
    active: bool | None = None

class MealUpdate(BaseModel):
    menu: str | None = None
    actual_cost: Decimal | None = Field(default=None, ge=0)
    reservation_deadline: datetime | None = None

class ReservationCreate(BaseModel):
    student_id: int
    meal_id: int
    reserve: bool = True

class RFIDTap(BaseModel):
    rfid_uid: str
    meal_id: int
    device_id: str = "mess-reader-1"

class ServeConfirm(BaseModel):
    collection_id: int
    staff_id: str = "staff-1"

class ExpenseCreate(BaseModel):
    meal_id: int | None = None
    category: str
    description: str = ""
    amount: Decimal = Field(gt=0)
