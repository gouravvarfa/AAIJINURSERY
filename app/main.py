import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from app import api_public

load_dotenv()

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.accounting.router import router as accounting_router
from app.communications import models as communications_models  # noqa: F401 -- registers tables with Base.metadata
from app.communications.router import router as communications_router
from app.communications.seed import seed_communications_defaults
from app.communications.worker import start_worker as start_whatsapp_worker
from app.delivery.router import router as delivery_router
from app.labour.router import router as labour_router
from app.database import Base, SessionLocal, engine
from app.live_logs.handler import LiveLogHandler
from app.live_logs.hub import hub as live_log_hub
from app.live_logs.router import router as live_logs_router
from app.order_alerts.hub import hub as order_alert_hub
from app.order_alerts.router import router as order_alerts_router
from app.monitoring.module_map import infer_module
from app.monitoring.recorder import record_error, record_request_outcome
from app.permissions import require_permission
from app.rbac_seed import seed_rbac_defaults
from app.routers import api_admin, api_admin_analytics, api_admin_rbac, api_customer, api_system_health
from app.seed_data import seed_if_empty

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

Base.metadata.create_all(bind=engine)

# Schema shims (ALTER TABLE for pre-existing tables) must run before
# seed_if_empty -- seeding queries ORM models whose Python class already
# declares newly-added columns, so the actual on-disk table must have them
# first or SQLAlchemy raises "no such column" on a fresh migration.
with engine.connect() as conn:
    existing_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(inquiries)"))}
    if "plant_id" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN plant_id INTEGER"))
        conn.commit()

    # Feature 1 (out-of-stock product enquiry): additive columns on the
    # existing Inquiry table, all nullable/defaulted so old generic
    # contact-form rows are completely unaffected.
    if "customer_id" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN customer_id INTEGER"))
        conn.commit()
    if "email" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN email VARCHAR(180) DEFAULT ''"))
        conn.commit()
    if "quantity" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN quantity INTEGER"))
        conn.commit()
    if "enquiry_number" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN enquiry_number VARCHAR(30)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_inquiries_enquiry_number ON inquiries(enquiry_number)"))
        conn.commit()
    if "plant_name_snapshot" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN plant_name_snapshot VARCHAR(150) DEFAULT ''"))
        conn.commit()
    if "updated_at" not in existing_columns:
        conn.execute(text("ALTER TABLE inquiries ADD COLUMN updated_at DATETIME"))
        conn.commit()

    plant_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plants)"))}
    if "availability_status" not in plant_columns:
        conn.execute(text("ALTER TABLE plants ADD COLUMN availability_status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE'"))
        conn.commit()

    admin_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(admin_users)"))}
    if "role" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'"))
        conn.commit()
    if "created_at" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN created_at DATETIME"))
        conn.commit()
    if "accounting_role" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN accounting_role VARCHAR(20)"))
        # Backfill every admin that existed before Phase 4 to Owner so nobody
        # who already had unrestricted Accounting access loses it -- only
        # admins created after this point default to NULL (-> Viewer).
        conn.execute(text("UPDATE admin_users SET accounting_role = 'Owner' WHERE accounting_role IS NULL"))
        conn.commit()
    conn.execute(text("UPDATE admin_users SET role = 'developer' WHERE username = 'lucky'"))
    conn.execute(text("UPDATE admin_users SET role = 'developer' WHERE username = 'admin'"))
    # 'lucky' is the site owner -- always ensure they hold the accounting
    # Owner role too, so they can never get locked out of Accounting Roles.
    conn.execute(text("UPDATE admin_users SET accounting_role = 'Owner' WHERE username = 'lucky'"))
    conn.commit()

    # Developer Dashboard RBAC: is_active defaults to 1, so every pre-existing
    # admin row is automatically backfilled to "active" -- nobody who could
    # log in before this column existed is locked out by its addition.
    if "is_active" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        conn.commit()
    if "locked_until" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN locked_until DATETIME"))
        conn.commit()
    if "failed_login_attempts" not in admin_columns:
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"))
        conn.commit()
    if "custom_role_id" not in admin_columns:
        # Nullable, stays NULL for every pre-existing row (they're
        # "admin"/"developer", never "custom") -- only used going forward.
        conn.execute(text("ALTER TABLE admin_users ADD COLUMN custom_role_id INTEGER"))
        conn.commit()

    customer_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(customers)"))}
    if "reset_token" not in customer_columns:
        conn.execute(text("ALTER TABLE customers ADD COLUMN reset_token VARCHAR(100)"))
        conn.commit()
    if "reset_token_expires" not in customer_columns:
        conn.execute(text("ALTER TABLE customers ADD COLUMN reset_token_expires DATETIME"))
        conn.commit()

    order_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(orders)"))}
    if "razorpay_order_id" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN razorpay_order_id VARCHAR(100)"))
        conn.commit()
    if "razorpay_payment_id" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN razorpay_payment_id VARCHAR(100)"))
        conn.commit()
    if "razorpay_signature" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN razorpay_signature VARCHAR(255)"))
        conn.commit()
    if "idempotency_key" not in order_columns:
        # Lets checkout() detect a network-retried submit (same key resubmitted
        # after the client never saw the first response) and return the
        # already-created order instead of placing a duplicate one.
        conn.execute(text("ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(64)"))
        conn.commit()

    # Feature 2 (delivery feasibility + team confirmation): additive Order
    # columns, all nullable/defaulted -- existing orders backfill to
    # team_confirmation_status='PENDING', which the confirm/reject and
    # verify-payment guards below all treat identically to a brand-new
    # order, so nothing about an already-placed order's real-world status
    # changes just because this migration ran.
    if "team_confirmation_status" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN team_confirmation_status VARCHAR(30) NOT NULL DEFAULT 'PENDING'"))
        # One-time cutover: every order that already exists was placed
        # under the old instant-checkout flow, where team confirmation was
        # never part of the deal -- backfill them all to CONFIRMED so this
        # migration can't retroactively block a real historical order (even
        # one still sitting at status='Pending') from being progressed.
        # Only orders placed AFTER this migration runs start at PENDING.
        conn.execute(text("UPDATE orders SET team_confirmation_status = 'CONFIRMED'"))
        conn.commit()
    if "delivery_feasibility" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_feasibility VARCHAR(30) NOT NULL DEFAULT 'PENDING'"))
        conn.commit()
    if "delivery_distance_km" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_distance_km FLOAT"))
        conn.commit()
    if "delivery_cost_calculated" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_cost_calculated FLOAT"))
        conn.commit()
    if "delivery_cost_mode" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_cost_mode VARCHAR(20) NOT NULL DEFAULT 'MANUAL'"))
        conn.commit()
    if "delivery_review_notes" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_review_notes TEXT DEFAULT ''"))
        conn.commit()
    if "delivery_rejection_reason" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_rejection_reason VARCHAR(200) DEFAULT ''"))
        conn.commit()
    if "team_confirmed_by" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN team_confirmed_by VARCHAR(80) DEFAULT ''"))
        conn.commit()
    if "team_confirmed_at" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN team_confirmed_at DATETIME"))
        conn.commit()

    # New Order Alert + Call Management: additive columns, all
    # nullable/defaulted. Existing orders backfill order_acknowledged=True
    # so historical orders don't retroactively show up in the "new orders"
    # alert queue the moment this migration runs.
    if "call_status" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN call_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'"))
        conn.commit()
    if "assigned_to" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN assigned_to VARCHAR(80) DEFAULT ''"))
        conn.commit()
    if "order_acknowledged" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN order_acknowledged BOOLEAN NOT NULL DEFAULT 0"))
        conn.execute(text("UPDATE orders SET order_acknowledged = 1"))
        conn.commit()
    if "acknowledged_by" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN acknowledged_by VARCHAR(80) DEFAULT ''"))
        conn.commit()
    if "acknowledged_at" not in order_columns:
        conn.execute(text("ALTER TABLE orders ADD COLUMN acknowledged_at DATETIME"))
        conn.commit()

    # Seedlings & Trays: cart_items needs a nullable variant_id, and its unique
    # constraint must widen to (customer_id, plant_id, variant_id) so a customer
    # can hold multiple tray sizes of the same seedling as separate cart lines.
    # SQLite bakes UNIQUE(...) into an unnamed autoindex, so it can't be dropped
    # by name -- rebuild the table instead (standard SQLite migration pattern).
    cart_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(cart_items)"))}
    if "variant_id" not in cart_columns:
        conn.execute(text("""
            CREATE TABLE cart_items_new (
                id INTEGER NOT NULL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                plant_id INTEGER NOT NULL,
                variant_id INTEGER,
                quantity INTEGER,
                created_at DATETIME,
                UNIQUE (customer_id, plant_id, variant_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO cart_items_new (id, customer_id, plant_id, variant_id, quantity, created_at)
            SELECT id, customer_id, plant_id, NULL, quantity, created_at FROM cart_items
        """))
        conn.execute(text("DROP TABLE cart_items"))
        conn.execute(text("ALTER TABLE cart_items_new RENAME TO cart_items"))
        conn.commit()

    order_item_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(order_items)"))}
    if "variant_id" not in order_item_columns:
        conn.execute(text("ALTER TABLE order_items ADD COLUMN variant_id INTEGER"))
        conn.commit()
    if "tray_size" not in order_item_columns:
        conn.execute(text("ALTER TABLE order_items ADD COLUMN tray_size INTEGER"))
        conn.commit()

    # Accounting module: extends the existing Purchase table (rather than a
    # duplicate "Bill" table) with status/due_date/source/contact_id. Existing
    # rows backfill to status='Paid' since every Purchase recorded before this
    # column existed represented an already-settled procurement event.
    purchase_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(purchases)"))}
    if "status" not in purchase_columns:
        conn.execute(text("ALTER TABLE purchases ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Paid'"))
        conn.commit()
    if "due_date" not in purchase_columns:
        conn.execute(text("ALTER TABLE purchases ADD COLUMN due_date DATETIME"))
        conn.commit()
    if "source" not in purchase_columns:
        conn.execute(text("ALTER TABLE purchases ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT 'offline'"))
        conn.commit()
    if "contact_id" not in purchase_columns:
        conn.execute(text("ALTER TABLE purchases ADD COLUMN contact_id INTEGER"))
        conn.commit()
    if "purchase_order_id" not in purchase_columns:
        conn.execute(text("ALTER TABLE purchases ADD COLUMN purchase_order_id INTEGER"))
        conn.commit()

    # Employee & Labour module: extends the existing accounting_employees
    # table (Phase 2's simple directory) with real HR/payroll fields. The
    # existing simple CRUD page/router keep working unchanged -- they just
    # never read or write these new columns.
    employee_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(accounting_employees)"))}
    if "department" not in employee_columns:
        conn.execute(text("ALTER TABLE accounting_employees ADD COLUMN department VARCHAR(100) DEFAULT ''"))
        conn.commit()
    if "overtime_rate" not in employee_columns:
        conn.execute(text("ALTER TABLE accounting_employees ADD COLUMN overtime_rate FLOAT DEFAULT 0"))
        conn.commit()
    if "status" not in employee_columns:
        conn.execute(text("ALTER TABLE accounting_employees ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Active'"))
        conn.commit()
    if "payment_method" not in employee_columns:
        conn.execute(text("ALTER TABLE accounting_employees ADD COLUMN payment_method VARCHAR(20) DEFAULT 'Cash'"))
        conn.commit()
    if "bank_details" not in employee_columns:
        conn.execute(text("ALTER TABLE accounting_employees ADD COLUMN bank_details TEXT DEFAULT ''"))
        conn.commit()

    # Communications: WhatsApp template approval-status enum (section: WhatsApp
    # Business Cloud API template system) supersedes the old is_active boolean
    # -- a template can now be PENDING/REJECTED/DISABLED, not just on/off.
    whatsapp_template_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(whatsapp_templates)"))}
    status_col_is_new = "status" not in whatsapp_template_columns
    if status_col_is_new:
        conn.execute(text("ALTER TABLE whatsapp_templates ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'PENDING'"))
        conn.commit()
    if "last_error" not in whatsapp_template_columns:
        conn.execute(text("ALTER TABLE whatsapp_templates ADD COLUMN last_error TEXT DEFAULT ''"))
        conn.commit()
    if "updated_at" not in whatsapp_template_columns:
        conn.execute(text("ALTER TABLE whatsapp_templates ADD COLUMN updated_at DATETIME"))
        conn.commit()
    if status_col_is_new:
        # One-time honest backfill against REAL evidence from live testing
        # this session -- never assume an old is_active=1 row is actually
        # Meta-approved (order_confirmed was marked is_active=1 for testing
        # but Meta genuinely rejected it as "does not exist in translation").
        # Every other pre-existing row starts at the safe default (PENDING),
        # never auto-promoted to ACTIVE without real confirmation.
        conn.execute(text("UPDATE whatsapp_templates SET status = 'ACTIVE' WHERE name = 'hello_world'"))
        conn.execute(text("UPDATE whatsapp_templates SET status = 'REJECTED', last_error = 'Meta: template name does not exist in the translation (en_US)' WHERE name = 'order_confirmed'"))
        conn.commit()

    # Communications: DRIVER recipient support + document (PDF) messages --
    # additive columns, existing CUSTOMER-only messages are completely
    # unaffected (recipient_type defaults to 'CUSTOMER', message_type stays
    # 'template' for every existing row).
    whatsapp_message_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(whatsapp_messages)"))}
    if "recipient_type" not in whatsapp_message_columns:
        conn.execute(text("ALTER TABLE whatsapp_messages ADD COLUMN recipient_type VARCHAR(10) NOT NULL DEFAULT 'CUSTOMER'"))
        conn.commit()
    if "recipient_id" not in whatsapp_message_columns:
        conn.execute(text("ALTER TABLE whatsapp_messages ADD COLUMN recipient_id INTEGER"))
        conn.commit()
    if "document_name" not in whatsapp_message_columns:
        conn.execute(text("ALTER TABLE whatsapp_messages ADD COLUMN document_name VARCHAR(200) DEFAULT ''"))
        conn.commit()
    if "media_id" not in whatsapp_message_columns:
        conn.execute(text("ALTER TABLE whatsapp_messages ADD COLUMN media_id VARCHAR(120) DEFAULT ''"))
        conn.commit()

seed_if_empty(SessionLocal)
seed_rbac_defaults(SessionLocal)
seed_communications_defaults(SessionLocal)

app = FastAPI(title="Aaiji Nursery")

# Live Logs (Developer Dashboard): attach the bridge handler to the ROOT
# logger so any existing `logger.info/.warning/.error(...)` call anywhere
# in the app -- not just new ones -- becomes visible in the live terminal.
# This does NOT change root's level (so third-party libraries stay exactly
# as quiet as before); it only adds a destination for whatever already
# passes each individual logger's own effective level.
logging.getLogger().addHandler(LiveLogHandler())


@app.on_event("startup")
async def _bind_live_log_hub():
    import asyncio
    live_log_hub.bind_loop(asyncio.get_running_loop())
    order_alert_hub.bind_loop(asyncio.get_running_loop())
    start_whatsapp_worker()


@app.get("/")
def serve_home():
    if FRONTEND_DIST.exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return {"message": "Frontend not built"}

SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    raise RuntimeError(
        "SESSION_SECRET_KEY environment variable is not set. "
        "Copy .env.example to .env and set a random secret before starting the server "
        "(login/admin sessions cannot be signed safely without it)."
    )

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

# Dev-only: allow the Vite dev server (or direct API calls) from localhost and
# any private LAN IP to hit this API with cookies, so a second laptop on the
# same Wi-Fi can be used for testing. Not safe for production as-is.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

request_logger = logging.getLogger("app.requests")
# Live Logs (Developer Dashboard): this is the single most reliable source
# of "watch the real backend terminal live" content in an app with no
# background-job system -- every real API request, as it really happens.
# Scoped to this one logger's level only (root's level is untouched) so no
# third-party library becomes noisier as a side effect.
request_logger.setLevel(logging.INFO)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = f"REQ-{datetime.utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    request.state.request_id = request_id
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        # Anything reaching here is a genuinely unhandled bug -- every
        # `raise HTTPException(...)` in the app (185 call sites) is already
        # converted to a clean JSONResponse by Starlette's own
        # ExceptionMiddleware, which sits between the router and this
        # middleware, so it never lands in this branch.
        elapsed_ms = (time.perf_counter() - start) * 1000
        module, sub_module, func_name, endpoint = infer_module(request)
        request_logger.exception(
            "unhandled error request_id=%s module=%s function=%s endpoint=%s",
            request_id, module, func_name, endpoint,
        )
        record_error(module, sub_module, func_name, endpoint, request.method, 500, request_id, exc, elapsed_ms)
        record_request_outcome(module, sub_module, func_name, endpoint, request.method, 500, request_id, elapsed_ms)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "detail": "Something went wrong on our end. Please try again in a moment.",
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Something went wrong on our end. Please try again in a moment.",
                },
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    elapsed_ms = (time.perf_counter() - start) * 1000
    module, sub_module, func_name, endpoint = infer_module(request)
    record_request_outcome(module, sub_module, func_name, endpoint, request.method, response.status_code, request_id, elapsed_ms)
    response.headers["X-Request-ID"] = request_id

    if request.url.path.startswith("/api"):  # skip static asset/SPA-fallback noise
        request_logger.info(
            "%s %s -> %s (%.0fms)",
            request.method, request.url.path, response.status_code, elapsed_ms,
            extra={"request_id": request_id, "service": module, "module_name": func_name},
        )
    return response


app.include_router(api_public.router)
app.include_router(live_logs_router)
app.include_router(order_alerts_router)
app.include_router(api_admin.router)
# Coarse module-VIEW enforcement (Developer Dashboard RBAC, Phase 4): every
# route in these already-standalone routers now additionally requires
# module-level VIEW permission -- the outer "can this admin enter this
# module at all" boundary. This changes nothing for existing admin/
# developer/super_access accounts (their seeded roles grant full VIEW
# access to every module); it only actually restricts a Custom role that
# wasn't given VIEW on that module. The existing accounting_role-based
# require_roles() write-gating inside these modules is untouched.
app.include_router(api_admin_analytics.router, dependencies=[Depends(require_permission("analytics", "VIEW"))])
app.include_router(api_admin_rbac.router)
app.include_router(api_system_health.router)
app.include_router(accounting_router, dependencies=[Depends(require_permission("accounting", "VIEW"))])
app.include_router(labour_router, dependencies=[Depends(require_permission("labour", "VIEW"))])
app.include_router(delivery_router, dependencies=[Depends(require_permission("delivery", "VIEW"))])
app.include_router(communications_router, dependencies=[Depends(require_permission("communications", "VIEW"))])
app.include_router(api_customer.router)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_react_app(full_path: str):
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST.resolve()):
            # Everything served through this catch-all (favicon.png, manifest,
            # robots.txt, sitemap.xml, ...) has a plain, non-hashed filename --
            # unlike /assets/*.js|css which get a content hash per build and
            # can be cached forever. Without an explicit header here, browsers
            # apply their own heuristic caching and can keep serving a stale
            # copy for a long time after a deploy (bit us with both the
            # favicon and an old JS bundle sticking around after real fixes
            # had already shipped).
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})





























