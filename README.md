# Smart Hostel Mess Management System

A runnable college-project MVP implementing the agreed **zero-extra-staff** workflow:

**Reserve → Prepare → RFID/QR → Identity + Photo → Existing Mess Worker Confirms Serving → Usage Billing → Balance → Audit/Analytics**

The design does **not** claim RFID proves that a student actually ate the food. RFID verifies identity/meal collection. The existing serving worker performs a quick visual check and presses **SERVE**. No dedicated verification employee is required.

This version is hardened specifically for deployment at a **tier-2 government college with limited infrastructure** -- unreliable power, patchy or no internet, a tight budget, and no dedicated IT staff. See [Deploying on low infrastructure](#deploying-on-low-infrastructure-tier-2-government-college) below.

## Anti-cheating design
- RFID reader is intended for the controlled serving point.
- After a tap, the serving screen/API returns student name, roll number, room and optional student photo.
- Existing mess worker visually matches the student to the displayed identity/photo and confirms **SERVE**.
- One collection per student per meal is enforced server-side.
- Tap, serving confirmation/rejection, device ID, staff ID and timestamps are stored as an audit trail.
- Tap without SERVE creates **no meal charge**.
- Repeated no-shows/rejections can be reviewed as unusual activity by management.
- The system cannot completely prevent a student from physically handing food to another person after receiving it. It can only make the collection event attributable and auditable.

## Zero-extra-staff principle
There is no separate verification employee. The normal mess worker who already serves food does one additional simple action: **SERVE** or **REJECT** after the system displays the student's identity/photo.

Student work: reserve in advance (via `/reserve` or the API) and tap RFID/QR.
Existing mess worker: log into the serving counter once, then verify identity visually and confirm serving.
System: validate reservation, block duplicates, calculate charges, maintain balances, track no-shows and produce reports.

## Included
- Student registration with unique RFID UID and optional photo
- Student record updates: **reissue a lost/damaged RFID card, deactivate a student who has left, fix room/phone/photo** (`PATCH /api/students/{id}`)
- Locally-stored student photos served from the same machine (`POST /api/students/{id}/photo`) -- no dependency on an external image host
- Meal/menu creation and configurable reservation deadline, with **actual cost editable after the fact** (`PATCH /api/meals/{id}`) since real ingredient spend is usually only known once service is done
- A lightweight, no-login **student reservation page** (`/reserve`) for students without a dedicated app -- plain HTML, works on any old phone browser
- RFID tap validation at the serving point
- Reservation enforcement (unreserved walk-ins denied)
- Duplicate meal collection prevention
- Two-step tap + existing staff confirmation
- Serving Counter page for the existing worker (`/serving-counter`), protected by staff login
- Student photo/identity display data after RFID tap
- Rejected tap creates no charge
- Actual-cost shared billing among verified served students
- Automatic charge rebalancing when actual cost is entered late or another student is served afterward
- **Fallback flat-rate billing** if a meal is closed and nobody entered its actual cost, so charges don't silently stay at zero from a missed data-entry step
- **Paper-fallback reconciliation**: bulk-import a CSV of a hand-written attendance sheet from a system-downtime period (`POST /api/collections/import`), safely skipping rows that would double-count
- Per-student ledger/balance
- No-show tracking when a meal is closed
- Expense recording
- Staff-only admin dashboard and serving counter, protected with HTTP Basic Auth
- Analytics endpoint
- Automated tests for core reservation, duplicate, anti-fraud, billing, auth, and paper-reconciliation cases
- SQLite by default (recommended for this deployment -- see below); SQLAlchemy allows switching to another database URL
- WAL journal mode enabled, so the database survives a sudden power cut far better than SQLite's default mode

## Important billing rule
This MVP uses **shared actual meal cost**: the meal's entered actual cost is divided among verified serving events. If cost data entry is missed and `DEFAULT_MEAL_RATE` is configured (see `.env.example`), that flat rate is applied automatically when the meal is closed, rather than leaving every student billed ₹0.00. Fixed hostel costs such as salaries/rent are not automatically inferred. If management needs firmer, more predictable revenue than shared-actual-cost gives you, consider a fixed monthly base contribution + variable meal charge instead.

## Deploying on low infrastructure (tier-2 government college)

**Keep SQLite. Don't "upgrade" to Postgres/MySQL.** For one mess counter, SQLite means no separate database server to install, configure, or keep alive -- one less thing that can fail with no IT staff around. WAL mode (already enabled) is also more resistant to corruption from a power cut than most people expect.

**Power**
- Put a small UPS (a couple thousand rupees, not a whole-building one) on just the machine running the server and its router. That is the only hardware that needs to survive a cut.
- Run the server under `deploy/smart-hostel-mess.service` (systemd) or `deploy/start.sh` (no-systemd fallback) so it comes back on its own after a crash or reboot, without anyone needing to notice and restart it by hand.
- Back up `mess.db` regularly: `python3 scripts/backup_db.py` (safe to run while the server is live; see the script for a cron/Task Scheduler example). This is the single most important defense against losing all mess data to a corrupted file or a dead disk.

**Connectivity**
- The RFID reader, the serving-counter device, and the server don't need internet at all -- only a local network. A dedicated, cheap local Wi-Fi router (no internet uplink required) is usually more reliable than depending on campus-wide Wi-Fi.
- Because that network is local and not exposed to the internet, plain HTTP from the ESP32 reader to the server is a reasonable simplification -- it avoids the certificate management that HTTPS would otherwise need on a device like an ESP32.
- Student photos are now stored on the server itself and served locally (`/static/photos/...`), not fetched from an external URL, so the serving counter still shows photos with zero internet access.

**When the system itself is down**
No software can prevent an outage. Keep a printed attendance sheet at the serving counter as a fallback; staff keep serving students by sight/ID as usual. Afterwards, a staff member reconciles the sheet with `POST /api/collections/import` (a CSV with `roll_number,meal_id,status` columns) so billing and audit history stay complete. Rows that don't match a known student/meal are reported back individually instead of failing the whole batch.

**Staff usability**
- The serving counter page (`/serving-counter`) is plain server-rendered HTML with large buttons -- it runs fine on an old Android phone or a hand-me-down laptop; there was never a need for a dedicated touchscreen kiosk.
- It is now behind a staff username/password (HTTP Basic Auth) so a passing student can't open it and press SERVE/REJECT themselves. **Change `STAFF_USERNAME`/`STAFF_PASSWORD` in your `.env` before deployment** -- the app prints a warning on startup if you leave the default password in place.

**Hardware cost baseline**: ESP32 + RC522 reader (~₹300-600/reader) is already the right call -- there's no need for anything fancier; the photo-display step at serving time does most of the impersonation-deterrence work that a much more expensive biometric reader would.

## Run on Linux (recommended for a low-cost deployment machine)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit STAFF_USERNAME/STAFF_PASSWORD at minimum
python run.py
```
Then install `deploy/smart-hostel-mess.service` (see comments in that file) so it survives reboots/crashes unattended.

## Run on Windows / PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open `http://<this-machine's-LAN-IP>:8000` from other devices on the mess-hall network (not `127.0.0.1`, which only works on the same machine), then `/serving-counter`, `/reserve`, and `/docs`.

## Tests
```bash
pytest -q
```
Covers the original reservation/duplicate/billing/anti-fraud cases plus the new auth, card-reissue, late-cost-entry, default-rate-fallback, and CSV-reconciliation behavior.

## API flow
1. `POST /api/students`
2. `POST /api/meals`
3. `POST /api/reservations` (or a student uses `/reserve`)
4. `POST /api/rfid/tap`
5. Existing worker checks identity/photo at `/serving-counter` (staff login required)
6. `POST /api/serve/confirm` or the `/serving-counter` SERVE button
7. `PATCH /api/meals/{id}` once actual cost is known, if not entered at creation
8. `GET /api/students/{id}/ledger`
9. `POST /api/meals/{id}/close` (applies the default-rate fallback if cost was never entered)
10. `GET /api/meals/{id}/stats`
11. `GET /api/analytics/overview`
12. If the system was down: `POST /api/collections/import` with the paper sheet as CSV

FastAPI Swagger UI at `/docs` can execute every API endpoint.

## Hardware integration
For an ESP32 + RC522 prototype, the microcontroller should send the scanned UID and meal ID to `/api/rfid/tap` over the local Wi-Fi network. Plain HTTP is acceptable here specifically because this network is local and not exposed to the internet (see Deploying on low infrastructure above); do not expose this server directly to the public internet over plain HTTP. Do not put billing logic in the ESP32 -- the server is the source of truth for reservations and duplicate prevention.

A practical serving-counter layout is:
**Mess entrance/serving point → RFID reader → worker screen with student identity/photo → food handover → SERVE**.

## Production hardening still required
- Full API-wide authentication/RBAC (currently, staff login protects the dashboard, serving counter, and record-editing endpoints; the core reservation/tap/serve API used by the ESP32 device is intentionally left open, matching its original design)
- Device credentials for the RFID reader itself (currently any device on the local network can call `/api/rfid/tap`)
- CSRF/session controls if this grows beyond simple server-rendered forms
- Database migrations (Alembic) if the schema needs to change after real data exists
- Monitoring/alerting beyond systemd's own restart behavior
- Strong cryptographic RFID cards if cloning resistance is required
- Leave integration (auto-cancel reservations for students on approved leave)
- Finance-system integration
- Real demand prediction and waste measurement
- Privacy/retention policy for student data

## Project structure
```
app/
  database.py
  main.py
  models.py
  schemas.py
  services.py
  static/
    photos/        # locally-stored student photos
tests/
  test_system.py
scripts/
  backup_db.py      # safe SQLite backup, run on a schedule
deploy/
  smart-hostel-mess.service   # systemd unit, auto-restart on crash/reboot
  start.sh                    # no-systemd fallback restart loop
requirements.txt
README.md
.env.example
```
