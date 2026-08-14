"""واجهات الفاتورة الإلكترونية — E-invoice endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.billing import Invoice
from app.models.enums import AuditAction, EtaStatus, InvoiceType
from app.schemas.common import ApiModel
from app.services import audit
from app.services import invoicing as inv

router = APIRouter(prefix="/invoices", tags=["الفاتورة الإلكترونية — E-Invoicing"])


# ═══════════════════════════════════════════════════════════ النماذج
class LineOut(ApiModel):
    line_number: int
    description_ar: str
    description_en: str | None = None
    item_code: str | None = None
    unit_type: str
    quantity: Decimal
    unit_price: Decimal
    sales_total: Decimal
    discount_amount: Decimal
    net_total: Decimal
    tax_percent: Decimal
    tax_amount: Decimal
    service_charge_amount: Decimal
    total: Decimal


class InvoiceOut(ApiModel):
    id: int
    number: str
    invoice_type: InvoiceType
    business_date: date
    issued_at: datetime
    folio_id: int | None = None
    pos_order_id: int | None = None
    reservation_id: int | None = None
    customer_name: str
    customer_tax_number: str | None = None
    customer_national_id: str | None = None
    customer_type: str
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    service_charge_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    eta_status: EtaStatus
    eta_uuid: str | None = None
    eta_internal_id: str | None = None
    eta_error_message: str | None = None
    eta_retry_count: int
    eta_submitted_at: datetime | None = None
    eta_accepted_at: datetime | None = None
    qr_payload: str | None = None
    is_cancelled: bool
    cancellation_reason: str | None = None
    credit_note_for_invoice_id: int | None = None
    lines: list[LineOut] = []


class InvoiceListItem(ApiModel):
    id: int
    number: str
    invoice_type: InvoiceType
    business_date: date
    issued_at: datetime
    customer_name: str
    grand_total: Decimal
    tax_total: Decimal
    eta_status: EtaStatus
    is_cancelled: bool
    eta_error_message: str | None = None


class StatsOut(ApiModel):
    total: int
    accepted: int
    pending: int
    failed: int
    rejected: int
    draft: int
    cancelled: int
    today_total: Decimal
    today_tax: Decimal
    eta_enabled: bool


class CancelIn(ApiModel):
    reason: str


class QueueResult(ApiModel):
    ok: bool = True
    message_ar: str
    message_en: str
    accepted: int = 0
    failed: int = 0
    requeued: int = 0


def _fail(exc: inv.InvoiceError) -> HTTPException:
    code = {
        "not_found": 404,
        "already_issued": 409,
        "already_cancelled": 409,
    }.get(exc.code, 400)
    return HTTPException(
        status_code=code, detail={"ar": exc.message_ar, "en": exc.message_en, "code": exc.code}
    )


def _out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        **{
            k: getattr(invoice, k)
            for k in (
                "id", "number", "invoice_type", "business_date", "issued_at", "folio_id",
                "pos_order_id", "reservation_id", "customer_name", "customer_tax_number",
                "customer_national_id", "customer_type", "currency", "subtotal",
                "discount_total", "service_charge_total", "tax_total", "grand_total",
                "eta_status", "eta_uuid", "eta_internal_id", "eta_error_message",
                "eta_retry_count", "eta_submitted_at", "eta_accepted_at", "qr_payload",
                "is_cancelled", "cancellation_reason", "credit_note_for_invoice_id",
            )
        },
        lines=[
            LineOut(
                line_number=l.line_number,
                description_ar=l.description_ar,
                description_en=l.description_en,
                item_code=l.item_code,
                unit_type=l.unit_type,
                quantity=l.quantity,
                unit_price=l.unit_price,
                sales_total=l.sales_total,
                discount_amount=l.discount_amount,
                net_total=l.net_total,
                tax_percent=l.tax_percent,
                tax_amount=l.tax_amount,
                service_charge_amount=l.service_charge_amount,
                total=l.total,
            )
            for l in sorted(invoice.lines, key=lambda x: x.line_number)
        ],
    )


# ═══════════════════════════════════════════════════════════ القراءة
@router.get(
    "",
    response_model=list[InvoiceListItem],
    summary="المستندات الضريبية",
    dependencies=[Depends(require("invoice.issue"))],
)
def list_invoices(
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    eta_status: EtaStatus | None = None,
    invoice_type: InvoiceType | None = None,
    search: str | None = None,
    limit: int = Query(default=60, ge=1, le=300),
) -> list[InvoiceListItem]:
    stmt = select(Invoice).where(Invoice.property_id == prop.id)
    if eta_status:
        stmt = stmt.where(Invoice.eta_status == eta_status)
    if invoice_type:
        stmt = stmt.where(Invoice.invoice_type == invoice_type)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            Invoice.number.ilike(needle) | Invoice.customer_name.ilike(needle)
        )

    rows = db.execute(stmt.order_by(Invoice.id.desc()).limit(limit)).scalars().all()
    return [
        InvoiceListItem(
            id=r.id,
            number=r.number,
            invoice_type=r.invoice_type,
            business_date=r.business_date,
            issued_at=r.issued_at,
            customer_name=r.customer_name,
            grand_total=r.grand_total,
            tax_total=r.tax_total,
            eta_status=r.eta_status,
            is_cancelled=r.is_cancelled,
            eta_error_message=r.eta_error_message,
        )
        for r in rows
    ]


@router.get(
    "/stats",
    response_model=StatsOut,
    summary="حالة المنظومة",
    dependencies=[Depends(require("invoice.issue"))],
)
def get_stats(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> StatsOut:
    s = inv.stats(db, prop.id)
    return StatsOut(
        total=s.total,
        accepted=s.accepted,
        pending=s.pending,
        failed=s.failed,
        rejected=s.rejected,
        draft=s.draft,
        cancelled=s.cancelled,
        today_total=s.today_total,
        today_tax=s.today_tax,
        eta_enabled=prop.eta_enabled,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceOut,
    summary="مستند بالتفصيل",
    dependencies=[Depends(require("invoice.issue"))],
)
def get_invoice(
    invoice_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty
) -> InvoiceOut:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.property_id != prop.id:
        raise HTTPException(
            status_code=404, detail={"ar": "المستند غير موجود", "en": "Invoice not found"}
        )
    invoice.printed_count += 1
    db.flush()
    return _out(invoice)


# ═══════════════════════════════════════════════════════════ الإصدار
@router.post(
    "/from-folio/{folio_id}",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="اطلع فاتورة من حساب نزيل",
    dependencies=[Depends(require("invoice.issue"))],
)
def issue_from_folio(
    folio_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty, request: Request
) -> InvoiceOut:
    try:
        invoice = inv.issue_for_folio(db, folio_id, user=user)
    except inv.InvoiceError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Invoice",
        entity_id=invoice.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إصدار فاتورة {invoice.number} بمبلغ {invoice.grand_total}",
        summary_en=f"Issued invoice {invoice.number}",
        request=request,
    )
    return _out(invoice)


@router.post(
    "/from-order/{order_id}",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="اطلع إيصال من أوردر",
    dependencies=[Depends(require("invoice.issue"))],
)
def issue_from_order(
    order_id: int, db: DbSession, user: CurrentUser, prop: CurrentProperty, request: Request
) -> InvoiceOut:
    try:
        invoice = inv.issue_for_pos_order(db, order_id, user=user)
    except inv.InvoiceError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.CREATE,
        entity_type="Invoice",
        entity_id=invoice.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إصدار إيصال {invoice.number} بمبلغ {invoice.grand_total}",
        summary_en=f"Issued receipt {invoice.number}",
        request=request,
    )
    return _out(invoice)


@router.post(
    "/{invoice_id}/cancel",
    response_model=InvoiceOut,
    summary="إشعار خصم يعكس الفاتورة",
    dependencies=[Depends(require("invoice.cancel"))],
)
def cancel_invoice(
    invoice_id: int,
    payload: CancelIn,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    request: Request,
) -> InvoiceOut:
    original = db.get(Invoice, invoice_id)
    if original is None or original.property_id != prop.id:
        raise HTTPException(
            status_code=404, detail={"ar": "المستند غير موجود", "en": "Invoice not found"}
        )
    try:
        note = inv.cancel(db, invoice_id, payload.reason, user=user)
    except inv.InvoiceError as exc:
        raise _fail(exc) from exc

    audit.record(
        db,
        action=AuditAction.VOID,
        entity_type="Invoice",
        entity_id=original.id,
        user=user,
        property_id=prop.id,
        summary_ar=f"إشعار خصم {note.number} يعكس {original.number} — {payload.reason}",
        summary_en=f"Credit note {note.number} reversing {original.number}",
        request=request,
    )
    return _out(note)


# ═══════════════════════════════════════════════════════ طابور المنظومة
@router.post(
    "/submit",
    response_model=QueueResult,
    summary="ابعت اللي في الطابور",
    dependencies=[Depends(require("invoice.issue"))],
)
def submit_queue(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> QueueResult:
    if not prop.eta_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "ar": "منظومة الفاتورة الإلكترونية مش مفعّلة في الإعدادات",
                "en": "ETA e-invoicing is not enabled in settings",
                "code": "eta_disabled",
            },
        )
    result = inv.submit_pending(db, prop.id)
    return QueueResult(
        message_ar=f"اتقبل {result.accepted} مستند · فشل {result.failed}",
        message_en=f"{result.accepted} accepted, {result.failed} failed",
        accepted=result.accepted,
        failed=result.failed,
    )


@router.post(
    "/retry",
    response_model=QueueResult,
    summary="رجّع المرفوض للطابور",
    dependencies=[Depends(require("invoice.issue"))],
)
def retry_queue(db: DbSession, user: CurrentUser, prop: CurrentProperty) -> QueueResult:
    back = inv.retry_rejected(db, prop.id)
    result = inv.submit_pending(db, prop.id)
    return QueueResult(
        message_ar=f"رجّعنا {back} مستند واتقبل منهم {result.accepted}",
        message_en=f"Requeued {back}, {result.accepted} accepted",
        requeued=back,
        accepted=result.accepted,
        failed=result.failed,
    )
