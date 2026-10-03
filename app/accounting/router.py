from fastapi import APIRouter

from app.accounting.router_accounts import router as accounts_router
from app.accounting.router_audit import router as audit_router
from app.accounting.router_bills import router as bills_router
from app.accounting.router_contacts import router as contacts_router
from app.accounting.router_employees import router as employees_router
from app.accounting.router_export import router as export_router
from app.accounting.router_expenses import router as expenses_router
from app.accounting.router_overview import router as overview_router
from app.accounting.router_parties import router as parties_router
from app.accounting.router_payments_out import router as payments_out_router
from app.accounting.router_pdf import router as pdf_router
from app.accounting.router_purchase_orders import router as purchase_orders_router
from app.accounting.router_reports import router as reports_router
from app.accounting.router_sales import router as sales_router
from app.accounting.router_tax_rates import router as tax_rates_router

router = APIRouter(prefix="/api/admin/accounting")
router.include_router(overview_router)
router.include_router(accounts_router)
router.include_router(tax_rates_router)
router.include_router(contacts_router)
router.include_router(parties_router)
router.include_router(sales_router)
router.include_router(purchase_orders_router)
router.include_router(bills_router)
router.include_router(expenses_router)
router.include_router(payments_out_router)
router.include_router(employees_router)
router.include_router(reports_router)
router.include_router(export_router)
router.include_router(pdf_router)
router.include_router(audit_router)
