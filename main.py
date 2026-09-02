import os
import csv
import io
import secrets
import shutil
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Student, Meal, Reservation, Collection, Expense, Transaction
from .schemas import StudentCreate, StudentUpdate, MealCreate, MealUpdate, ReservationCreate, RFIDTap, ServeConfirm, ExpenseCreate
from .services import update_balance, recalculate_meal_charges, finalize_no_shows, finalize_meal_billing, meal_stats

app = FastAPI(title="Smart Hostel Mess Management System", version="1.2.0")

STATIC_DIR = Path(__file__).parent / "static"
PHOTOS_DIR = STATIC_DIR / "photos"

# --- Staff auth (HTTP Basic) -------------------------------------------
# Deliberately simple: no session/login system to maintain, works in any
# browser, good enough to stop a random student from opening the admin
# page or the serving counter. Not a substitute for real RBAC if this
# grows beyond one mess hall.
security = HTTPBasic()
STAFF_USERNAME = os.getenv("STAFF_USERNAME", "staff")
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "changeme")

def require_staff_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    valid_user = secrets.compare_digest(credentials.username, STAFF_USERNAME)
    valid_pass = secrets.compare_digest(credentials.password, STAFF_PASSWORD)
    if not (valid_user and valid_pass):
        raise HTTPException(status_code=401, detail="Incorrect staff username or password", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    if STAFF_PASSWORD == "changeme":
        print("WARNING: STAFF_PASSWORD is still the default 'changeme'. Set STAFF_USERNAME/STAFF_PASSWORD before real deployment.")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html><head><title>Smart Hostel Mess</title><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{font-family:Arial;max-width:900px;margin:30px auto;padding:0 16px}a{display:inline-block;padding:12px 16px;margin:6px;background:#111;color:#fff;text-decoration:none;border-radius:8px}.card{border:1px solid #ddd;padding:16px;border-radius:10px;margin:10px 0}</style></head><body><h1>Smart Hostel Mess Management</h1><div class='card'><b>Reserve → Prepare → RFID/QR → Identity + Photo → Existing Staff Confirm → Bill → Audit</b><p>No dedicated verification employee is required. The existing serving worker only confirms that the displayed student is the person receiving the meal.</p></div><a href='/reserve'>Reserve a Meal</a><a href='/docs'>API Docs</a><a href='/dashboard'>Dashboard</a><a href='/serving-counter'>Serving Counter</a></body></html>"""

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    students = db.scalar(select(func.count(Student.id))) or 0
    meals = db.scalar(select(func.count(Meal.id))) or 0
    collections = db.scalar(select(func.count(Collection.id)).where(Collection.status=="served")) or 0
    pending = db.scalar(select(func.count(Collection.id)).where(Collection.status=="tapped")) or 0
    return f"<html><body style='font-family:Arial;max-width:800px;margin:30px auto'><h1>Admin Dashboard</h1><p>Students: <b>{students}</b></p><p>Meals: <b>{meals}</b></p><p>Verified collections: <b>{collections}</b></p><p>Pending staff confirmations: <b>{pending}</b></p><p><a href='/docs'>Open API documentation</a></p></body></html>"

@app.post("/api/students", status_code=201)
def create_student(data: StudentCreate, db: Session=Depends(get_db)):
    if db.scalar(select(Student).where(Student.roll_number==data.roll_number)) or db.scalar(select(Student).where(Student.rfid_uid==data.rfid_uid)):
        raise HTTPException(409, "Roll number or RFID already exists")
    s=Student(**data.model_dump()); db.add(s); db.commit(); db.refresh(s)
    return {"id":s.id, "name":s.name, "roll_number":s.roll_number, "rfid_uid":s.rfid_uid, "balance":str(s.balance)}

@app.get("/api/students")
def list_students(db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    return [{"id":s.id,"name":s.name,"roll_number":s.roll_number,"room_number":s.room_number,"rfid_uid":s.rfid_uid,"photo_url":s.photo_url,"active":s.active,"balance":str(s.balance)} for s in db.scalars(select(Student).order_by(Student.name)).all()]

@app.patch("/api/students/{student_id}")
def update_student(student_id: int, data: StudentUpdate, db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    """Reissue a lost/damaged RFID card, deactivate a student who has left, fix a room/phone, etc."""
    s = db.get(Student, student_id)
    if not s: raise HTTPException(404, "Student not found")
    updates = data.model_dump(exclude_unset=True)
    if "rfid_uid" in updates and updates["rfid_uid"] != s.rfid_uid:
        if db.scalar(select(Student).where(Student.rfid_uid==updates["rfid_uid"], Student.id!=student_id)):
            raise HTTPException(409, "That RFID UID is already assigned to another student")
    if "roll_number" in updates and updates["roll_number"] != s.roll_number:
        if db.scalar(select(Student).where(Student.roll_number==updates["roll_number"], Student.id!=student_id)):
            raise HTTPException(409, "That roll number is already assigned to another student")
    for k, v in updates.items():
        setattr(s, k, v)
    db.commit(); db.refresh(s)
    return {"id":s.id,"name":s.name,"roll_number":s.roll_number,"room_number":s.room_number,"rfid_uid":s.rfid_uid,"phone":s.phone,"photo_url":s.photo_url,"active":s.active,"balance":str(s.balance)}

@app.post("/api/students/{student_id}/photo")
def upload_student_photo(student_id: int, file: UploadFile = File(...), db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    """Stores the photo locally under app/static/photos and points photo_url at it,
    instead of relying on an external URL that may be unreachable with poor internet."""
    s = db.get(Student, student_id)
    if not s: raise HTTPException(404, "Student not found")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(422, "Photo must be .jpg, .jpeg, .png or .webp")
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PHOTOS_DIR / f"{student_id}{ext}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    s.photo_url = f"/static/photos/{student_id}{ext}"
    db.commit()
    return {"student_id": student_id, "photo_url": s.photo_url}

@app.post("/api/meals", status_code=201)
def create_meal(data: MealCreate, db: Session=Depends(get_db)):
    if data.meal_type.lower() not in {"breakfast","lunch","dinner"}: raise HTTPException(422,"meal_type must be breakfast, lunch or dinner")
    if db.scalar(select(Meal).where(Meal.meal_date==data.meal_date, Meal.meal_type==data.meal_type.lower())): raise HTTPException(409,"Meal already exists")
    m=Meal(**data.model_dump()); m.meal_type=m.meal_type.lower(); db.add(m); db.commit(); db.refresh(m)
    return {"id":m.id,"meal_date":str(m.meal_date),"meal_type":m.meal_type,"menu":m.menu,"actual_cost":str(m.actual_cost)}

@app.get("/api/meals")
def list_meals(db: Session=Depends(get_db)):
    return [{"id":m.id,"meal_date":str(m.meal_date),"meal_type":m.meal_type,"menu":m.menu,"actual_cost":str(m.actual_cost),"closed":m.closed,"stats":meal_stats(db,m.id)} for m in db.scalars(select(Meal).order_by(Meal.meal_date.desc(), Meal.id.desc())).all()]

@app.patch("/api/meals/{meal_id}")
def update_meal(meal_id: int, data: MealUpdate, db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    """Enter/correct actual_cost after the fact -- real ingredient spend is
    usually only known once service is done, and this is now the only way
    to record it (there was previously no update route at all)."""
    m = db.get(Meal, meal_id)
    if not m: raise HTTPException(404, "Meal not found")
    updates = data.model_dump(exclude_unset=True)
    cost_changed = "actual_cost" in updates and updates["actual_cost"] is not None and Decimal(updates["actual_cost"]) != Decimal(m.actual_cost or 0)
    for k, v in updates.items():
        if v is not None:
            setattr(m, k, v)
    db.flush()
    if cost_changed:
        recalculate_meal_charges(db, meal_id)
    db.commit(); db.refresh(m)
    return {"id":m.id,"meal_date":str(m.meal_date),"meal_type":m.meal_type,"menu":m.menu,"actual_cost":str(m.actual_cost),"closed":m.closed}

@app.post("/api/reservations")
def reserve(data: ReservationCreate, db: Session=Depends(get_db)):
    s=db.get(Student,data.student_id); m=db.get(Meal,data.meal_id)
    if not s or not s.active: raise HTTPException(404,"Active student not found")
    if not m: raise HTTPException(404,"Meal not found")
    if m.closed: raise HTTPException(400,"Meal is closed")
    if m.reservation_deadline and datetime.utcnow() > m.reservation_deadline: raise HTTPException(400,"Reservation deadline has passed")
    r=db.scalar(select(Reservation).where(Reservation.student_id==s.id,Reservation.meal_id==m.id))
    if not data.reserve:
        if r: r.status="cancelled"
        else: r=Reservation(student_id=s.id,meal_id=m.id,status="cancelled"); db.add(r)
    else:
        if r: r.status="reserved"
        else: db.add(Reservation(student_id=s.id,meal_id=m.id,status="reserved"))
    db.commit()
    return {"student_id":s.id,"meal_id":m.id,"status":"reserved" if data.reserve else "cancelled"}

@app.get("/reserve", response_class=HTMLResponse)
def reserve_page(db: Session=Depends(get_db)):
    """Lightweight, no-login reservation page for students without a dedicated
    app -- plain HTML form, works on any old phone browser."""
    upcoming = db.scalars(select(Meal).where(Meal.closed==False).order_by(Meal.meal_date.asc(), Meal.id.asc())).all()
    cards=[]
    for m in upcoming:
        deadline = m.reservation_deadline.strftime('%d %b, %I:%M %p') if m.reservation_deadline else 'No deadline set'
        cards.append(f"<div class='card'><h3>{m.meal_type.title()} — {m.meal_date}</h3><p>{m.menu or 'Menu not posted yet'}</p><p>Reserve by: {deadline}</p><form method='post' action='/reserve/{m.id}'><input name='roll_number' placeholder='Your roll number' required style='padding:9px;width:55%;border-radius:6px;border:1px solid #ccc'><button name='reserve' value='yes' style='padding:9px 14px;margin-left:6px;border:0;border-radius:6px;background:#111;color:#fff'>I will eat</button> <button name='reserve' value='no' style='padding:9px 14px;border:0;border-radius:6px;background:#888;color:#fff'>Not eating</button></form></div>")
    body = ''.join(cards) or "<div class='card'>No upcoming meals open for reservation.</div>"
    return f"""<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Reserve a Meal</title><style>body{{font-family:Arial;max-width:600px;margin:20px auto;padding:0 14px}}.card{{border:1px solid #ddd;border-radius:10px;padding:14px;margin:10px 0}}</style></head><body><h1>Reserve Your Meal</h1><p>Enter your roll number and choose for each meal below.</p>{body}<p><a href='/'>Home</a></p></body></html>"""

@app.post("/reserve/{meal_id}", response_class=HTMLResponse)
def reserve_submit(meal_id: int, roll_number: str = Form(...), reserve: str = Form(...), db: Session=Depends(get_db)):
    s = db.scalar(select(Student).where(Student.roll_number==roll_number.strip(), Student.active==True))
    if not s:
        return HTMLResponse("<html><body style='font-family:Arial;max-width:500px;margin:30px auto'><h2>Roll number not found</h2><p>Check with the mess office if this looks wrong.</p><a href='/reserve'>Back</a></body></html>", status_code=404)
    m = db.get(Meal, meal_id)
    if not m or m.closed:
        return HTMLResponse("<html><body style='font-family:Arial;max-width:500px;margin:30px auto'><h2>This meal is no longer open</h2><a href='/reserve'>Back</a></body></html>", status_code=400)
    if m.reservation_deadline and datetime.utcnow() > m.reservation_deadline:
        return HTMLResponse("<html><body style='font-family:Arial;max-width:500px;margin:30px auto'><h2>Reservation deadline has passed</h2><a href='/reserve'>Back</a></body></html>", status_code=400)
    r = db.scalar(select(Reservation).where(Reservation.student_id==s.id, Reservation.meal_id==meal_id))
    want = reserve == "yes"
    if r: r.status = "reserved" if want else "cancelled"
    else: db.add(Reservation(student_id=s.id, meal_id=meal_id, status="reserved" if want else "cancelled"))
    db.commit()
    msg = "You're marked as eating" if want else "You're marked as not eating"
    return HTMLResponse(f"<html><body style='font-family:Arial;max-width:500px;margin:30px auto'><h2>{msg}</h2><p>{m.meal_type.title()} — {m.meal_date}</p><a href='/reserve'>Back to meals</a></body></html>")

@app.post("/api/rfid/tap")
def rfid_tap(data: RFIDTap, db: Session=Depends(get_db)):
    s=db.scalar(select(Student).where(Student.rfid_uid==data.rfid_uid,Student.active==True))
    m=db.get(Meal,data.meal_id)
    if not s: raise HTTPException(404,"Unknown or inactive RFID")
    if not m: raise HTTPException(404,"Meal not found")
    existing=db.scalar(select(Collection).where(Collection.student_id==s.id,Collection.meal_id==m.id))
    if existing and existing.status in {"tapped","served"}: raise HTTPException(409,"Meal already tapped/served")
    r=db.scalar(select(Reservation).where(Reservation.student_id==s.id,Reservation.meal_id==m.id,Reservation.status=="reserved"))
    if not r: raise HTTPException(403,"No valid reservation for this meal")
    c=Collection(student_id=s.id,meal_id=m.id,device_id=data.device_id,status="tapped"); db.add(c); db.commit(); db.refresh(c)
    return {"collection_id":c.id,"student":{"id":s.id,"name":s.name,"roll_number":s.roll_number,"room_number":s.room_number,"photo_url":s.photo_url},"status":"tapped","verification":{"identity":"rfid_verified","photo_check_required":True,"staff_confirmation_required":True},"message":"Identity verified. Show the student details/photo to the existing serving worker. Billing occurs only after SERVE confirmation."}

@app.get("/api/serving-counter/pending")
def serving_counter_pending(db: Session=Depends(get_db)):
    rows=db.scalars(select(Collection).where(Collection.status=="tapped").order_by(Collection.tapped_at.asc())).all()
    return [{"collection_id":c.id,"meal_id":c.meal_id,"tapped_at":c.tapped_at.isoformat(),"device_id":c.device_id,"student":{"id":c.student.id,"name":c.student.name,"roll_number":c.student.roll_number,"room_number":c.student.room_number,"photo_url":c.student.photo_url},"instruction":"Visually match the student to the displayed identity/photo, then confirm SERVE. No extra verification employee is required."} for c in rows]

@app.get("/serving-counter", response_class=HTMLResponse)
def serving_counter(db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    rows=db.scalars(select(Collection).where(Collection.status=="tapped").order_by(Collection.tapped_at.asc())).all()
    cards=[]
    for c in rows:
        photo = (f"<img src='{c.student.photo_url}' alt='Student photo' style='width:90px;height:90px;object-fit:cover;border-radius:8px'>" if c.student.photo_url else "<div style='width:90px;height:90px;border:1px solid #ccc;display:flex;align-items:center;justify-content:center'>No photo</div>")
        cards.append(f"<div class='card'><div style='display:flex;gap:16px;align-items:center'>{photo}<div><h3>{c.student.name}</h3><p>Roll: {c.student.roll_number} | Room: {c.student.room_number}</p><p>Collection #{c.id} | Meal #{c.meal_id}</p></div></div><p><b>Check identity/photo before serving.</b></p><form method='post' action='/serving-counter/confirm/{c.id}' style='display:inline'><button>✓ SERVE</button></form> <form method='post' action='/serving-counter/reject/{c.id}' style='display:inline'><button>✕ REJECT</button></form></div>")
    body=''.join(cards) or "<div class='card'>No students waiting for serving confirmation.</div>"
    return f"""<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Serving Counter</title><style>body{{font-family:Arial;max-width:900px;margin:20px auto;padding:0 14px}}.card{{border:1px solid #ddd;border-radius:10px;padding:16px;margin:12px 0}}button{{padding:10px 16px;margin:4px;border:0;border-radius:7px;cursor:pointer}}h1{{margin-bottom:4px}}</style></head><body><h1>Serving Counter</h1><p>Use the existing mess worker. No separate verification staff.</p>{body}<p><a href='/serving-counter'>Refresh</a> · <a href='/dashboard'>Admin dashboard</a></p></body></html>"""

@app.post("/serving-counter/confirm/{collection_id}", response_class=HTMLResponse)
def serving_counter_confirm(collection_id:int, db:Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    c=db.get(Collection,collection_id)
    if not c: raise HTTPException(404,"Collection event not found")
    if c.status!="tapped": raise HTTPException(409,"Collection is not pending")
    c.status="served"; c.served_at=datetime.utcnow(); c.staff_id=staff_user
    db.flush(); recalculate_meal_charges(db,c.meal_id); db.commit()
    return HTMLResponse("<html><body style='font-family:Arial;max-width:700px;margin:30px auto'><h2>Meal marked as served</h2><p>Billing has been recorded.</p><a href='/serving-counter'>Back to serving counter</a></body></html>")

@app.post("/serving-counter/reject/{collection_id}", response_class=HTMLResponse)
def serving_counter_reject(collection_id:int, db:Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    c=db.get(Collection,collection_id)
    if not c: raise HTTPException(404,"Collection event not found")
    if c.status!="tapped": raise HTTPException(409,"Collection is not pending")
    c.status="rejected"; c.staff_id=staff_user; db.commit()
    return HTMLResponse("<html><body style='font-family:Arial;max-width:700px;margin:30px auto'><h2>Serving rejected</h2><p>No meal charge was created.</p><a href='/serving-counter'>Back to serving counter</a></body></html>")

@app.post("/api/serve/confirm")
def confirm_serving(data: ServeConfirm, db: Session=Depends(get_db)):
    c=db.get(Collection,data.collection_id)
    if not c: raise HTTPException(404,"Collection event not found")
    if c.status!="tapped": raise HTTPException(409,"Collection is not pending")
    c.status="served"; c.served_at=datetime.utcnow(); c.staff_id=data.staff_id
    db.flush()
    per=recalculate_meal_charges(db,c.meal_id)
    db.commit()
    db.refresh(c)
    return {"collection_id":c.id,"status":"served","charge":str(c.charge),"current_equal_share_estimate":str(per)}

@app.post("/api/serve/reject")
def reject_serving(collection_id:int, db:Session=Depends(get_db)):
    c=db.get(Collection,collection_id)
    if not c: raise HTTPException(404,"Collection event not found")
    if c.status!="tapped": raise HTTPException(409,"Collection is not pending")
    c.status="rejected"; db.commit(); return {"collection_id":c.id,"status":"rejected"}

@app.post("/api/meals/{meal_id}/close")
def close_meal(meal_id:int, db:Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    m=db.get(Meal,meal_id)
    if not m: raise HTTPException(404,"Meal not found")
    finalize_no_shows(db,meal_id)
    used_fallback = finalize_meal_billing(db,meal_id)
    m.closed=True; db.commit()
    result={"meal_id":meal_id,"closed":True,"stats":meal_stats(db,meal_id)}
    if used_fallback:
        result["note"]="actual_cost was never entered for this meal; the configured DEFAULT_MEAL_RATE fallback was applied instead."
    return result

@app.get("/api/meals/{meal_id}/stats")
def stats(meal_id:int, db:Session=Depends(get_db)):
    if not db.get(Meal,meal_id): raise HTTPException(404,"Meal not found")
    st=meal_stats(db,meal_id); st["show_rate_percent"]=round((st["served"]/st["reserved"]*100) if st["reserved"] else 0,2); return st

@app.post("/api/expenses", status_code=201)
def add_expense(data:ExpenseCreate, db:Session=Depends(get_db)):
    if data.meal_id and not db.get(Meal,data.meal_id): raise HTTPException(404,"Meal not found")
    e=Expense(**data.model_dump()); db.add(e); db.commit(); db.refresh(e); return {"id":e.id,"amount":str(e.amount)}

@app.get("/api/students/{student_id}/ledger")
def ledger(student_id:int, db:Session=Depends(get_db)):
    s=db.get(Student,student_id)
    if not s: raise HTTPException(404,"Student not found")
    txns=db.scalars(select(Transaction).where(Transaction.student_id==student_id).order_by(Transaction.created_at.desc(),Transaction.id.desc())).all()
    return {"student":{"id":s.id,"name":s.name,"roll_number":s.roll_number},"balance":str(s.balance),"transactions":[{"id":t.id,"amount":str(t.amount),"type":t.txn_type,"description":t.description,"created_at":t.created_at.isoformat()} for t in txns]}

@app.get("/api/analytics/overview")
def analytics(db:Session=Depends(get_db)):
    served=db.scalar(select(func.count(Collection.id)).where(Collection.status=="served")) or 0
    reserved=db.scalar(select(func.count(Reservation.id)).where(Reservation.status=="reserved")) or 0
    no_show=db.scalar(select(func.count(Reservation.id)).where(Reservation.status=="no_show")) or 0
    total_cost=db.scalar(select(func.coalesce(func.sum(Meal.actual_cost),0))) or Decimal("0")
    return {"students":db.scalar(select(func.count(Student.id))) or 0,"meals":db.scalar(select(func.count(Meal.id))) or 0,"reserved_events":reserved,"served_events":served,"no_show_events":no_show,"meal_cost_total":str(total_cost),"overall_show_rate_percent":round(served/reserved*100,2) if reserved else 0}

@app.post("/api/collections/import")
def import_manual_collections(file: UploadFile = File(...), db: Session=Depends(get_db), staff_user: str = Depends(require_staff_auth)):
    """Reconcile a paper attendance sheet used while the system was down.
    CSV columns: roll_number,meal_id,status (status is 'served' or 'rejected', defaults to 'served').
    Skips rows that would duplicate an existing collection instead of failing the whole batch."""
    raw = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    created, skipped, errors = 0, 0, []
    affected_meal_ids = set()
    for i, row in enumerate(reader, start=2):
        roll = (row.get("roll_number") or "").strip()
        meal_id_raw = (row.get("meal_id") or "").strip()
        status = (row.get("status") or "served").strip().lower()
        status = status if status in {"served","rejected"} else "served"
        if not roll or not meal_id_raw:
            errors.append(f"Row {i}: missing roll_number or meal_id"); continue
        try:
            meal_id = int(meal_id_raw)
        except ValueError:
            errors.append(f"Row {i}: invalid meal_id '{meal_id_raw}'"); continue
        student = db.scalar(select(Student).where(Student.roll_number==roll))
        if not student:
            errors.append(f"Row {i}: unknown roll_number '{roll}'"); continue
        if not db.get(Meal, meal_id):
            errors.append(f"Row {i}: unknown meal_id {meal_id}"); continue
        if db.scalar(select(Collection).where(Collection.student_id==student.id, Collection.meal_id==meal_id)):
            skipped += 1; continue
        db.add(Collection(student_id=student.id, meal_id=meal_id, device_id="manual-paper-import", staff_id=staff_user, status=status, served_at=datetime.utcnow() if status=="served" else None))
        affected_meal_ids.add(meal_id)
        created += 1
    db.commit()
    for mid in affected_meal_ids:
        recalculate_meal_charges(db, mid)
    db.commit()
    return {"created":created, "skipped_existing":skipped, "errors":errors, "meals_recalculated":sorted(affected_meal_ids)}
