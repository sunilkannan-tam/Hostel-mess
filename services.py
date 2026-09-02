import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import Student, Meal, Reservation, Collection, Transaction, Expense

MONEY = Decimal("0.01")

def money(v):
    return Decimal(v).quantize(MONEY, rounding=ROUND_HALF_UP)

def update_balance(db: Session, student_id: int, amount: Decimal, txn_type: str, description: str):
    s = db.get(Student, student_id)
    if not s: raise ValueError("Student not found")
    s.balance = money(Decimal(s.balance or 0) + amount)
    db.add(Transaction(student_id=student_id, amount=amount, txn_type=txn_type, description=description))
    return s.balance

def recalculate_meal_charges(db: Session, meal_id: int):
    meal = db.get(Meal, meal_id)
    if not meal: raise ValueError("Meal not found")
    served = db.scalars(select(Collection).where(Collection.meal_id==meal_id, Collection.status=="served").order_by(Collection.id)).all()
    if not served:
        return Decimal("0.00")
    per = money(Decimal(meal.actual_cost or 0) / Decimal(len(served)))
    # reverse old charges before applying current split
    for c in served:
        if Decimal(c.charge or 0) != Decimal("0.00"):
            update_balance(db, c.student_id, -Decimal(c.charge), "billing_reversal", f"Rebalance {meal.meal_type} {meal.meal_date}")
            c.charge = Decimal("0.00")
    running = Decimal("0.00")
    for idx, c in enumerate(served):
        charge = per
        if idx == len(served)-1:
            charge = money(Decimal(meal.actual_cost or 0) - running)
        c.charge = charge
        running += charge
        update_balance(db, c.student_id, charge, "meal_charge", f"{meal.meal_type} {meal.meal_date}")
    db.flush()
    return per

def finalize_meal_billing(db: Session, meal_id: int) -> bool:
    """Called when a meal is closed. Real ingredient cost is often only
    known after service ends, so this is the last chance to bill it
    correctly. If nobody ever entered actual_cost (it is still 0.00) and
    a DEFAULT_MEAL_RATE is configured, apply rate * served_count instead
    of leaving every student's charge at zero because of a missed data
    entry step. Returns True if the fallback rate was used."""
    meal = db.get(Meal, meal_id)
    if not meal:
        raise ValueError("Meal not found")
    used_fallback = False
    default_rate = os.getenv("DEFAULT_MEAL_RATE", "").strip()
    if Decimal(meal.actual_cost or 0) == Decimal("0.00") and default_rate:
        served_count = db.scalar(select(func.count(Collection.id)).where(Collection.meal_id==meal_id, Collection.status=="served")) or 0
        if served_count > 0:
            meal.actual_cost = money(Decimal(default_rate) * served_count)
            used_fallback = True
    recalculate_meal_charges(db, meal_id)
    return used_fallback

def finalize_no_shows(db: Session, meal_id: int):
    reservations = db.scalars(select(Reservation).where(Reservation.meal_id==meal_id, Reservation.status=="reserved")).all()
    for r in reservations:
        c = db.scalar(select(Collection).where(Collection.student_id==r.student_id, Collection.meal_id==meal_id, Collection.status=="served"))
        if not c:
            r.status = "no_show"
    return reservations

def meal_stats(db: Session, meal_id: int):
    reserved = db.scalar(select(func.count(Reservation.id)).where(Reservation.meal_id==meal_id, Reservation.status=="reserved")) or 0
    served = db.scalar(select(func.count(Collection.id)).where(Collection.meal_id==meal_id, Collection.status=="served")) or 0
    tapped = db.scalar(select(func.count(Collection.id)).where(Collection.meal_id==meal_id, Collection.status=="tapped")) or 0
    no_show = db.scalar(select(func.count(Reservation.id)).where(Reservation.meal_id==meal_id, Reservation.status=="no_show")) or 0
    return {"reserved": reserved, "served": served, "tapped_pending": tapped, "no_show": no_show}
