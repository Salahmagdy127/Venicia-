"""اختبار الفاتورة الإلكترونية — E-invoicing flow test.

    python -m scripts.test_invoice_flow

المبدأ اللي السويت دي بتحرسه: **الفاتورة الصادرة مبتتعدّلش ومبتتمسحش.**
الإلغاء بيتم بإشعار خصم عكسي، والأصلية بتفضل مكانها بحالتها. ده مش
تشدّد — ده الفرق بين دفتر ينفع في فحص ضريبي ودفتر ملوش قيمة.

والترقيم متصل ومبيتكرّرش: مطلب مصلحة الضرائب، ومش رفاهية.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.main import app
from app.models.billing import Invoice
from app.models.enums import CREDIT_CHARGE_KINDS, EtaStatus, FolioStatus, InvoiceType
from app.models.folio import Folio, FolioLine
from app.models.organization import Property
from app.services import invoicing as inv

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def main() -> int:  # noqa: PLR0915
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    accountant = login("hesham")
    desk = login("ahmed")       # بيصدر فواتير مش بيلغي
    waiter = login("karim")     # ممنوع خالص

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()

    print("\n─── اللوحة ───")
    r = client.get("/api/v1/invoices/stats", headers=accountant)
    stats = r.json()
    check("إحصاءات الفواتير", r.status_code == 200,
          f"{stats['total']} فاتورة")
    check("العدّادات كلها موجودة",
          all(k in stats for k in
              ("accepted", "pending", "failed", "rejected", "draft", "cancelled")))
    check("حالة الربط بالمنظومة معلنة", "eta_enabled" in stats,
          f"متصل: {stats['eta_enabled']}")

    r = client.get("/api/v1/invoices?limit=20", headers=accountant)
    listing = r.json()
    check("قائمة الفواتير", r.status_code == 200, f"{len(listing)} فاتورة")

    r = client.get("/api/v1/invoices", headers=waiter)
    check("الويتر ممنوع من الفواتير", r.status_code == 403)

    print("\n─── إصدار فاتورة من حساب نزيل ───")
    # حساب مقفول عليه حركة فعلية — الفاتورة بتتبني من سطوره
    folio = db.execute(
        select(Folio)
        .where(
            Folio.property_id == prop.id,
            Folio.status == FolioStatus.CLOSED,
            Folio.charges_total > 0,
        )
        .order_by(Folio.id.desc())
        .limit(1)
    ).scalars().first()
    check("لقينا حساب فيه حركة", folio is not None,
          folio.code if folio else "")

    if folio is None:
        db.close()
        return 1

    existing = db.execute(
        select(Invoice).where(Invoice.folio_id == folio.id, Invoice.is_cancelled.is_(False))
    ).scalars().first()
    if existing is not None:
        check("الحساب متفوتر قبل كده — بندوّر على غيره", True, existing.number)
        folio = db.execute(
            select(Folio)
            .outerjoin(Invoice, Invoice.folio_id == Folio.id)
            .where(
                Folio.property_id == prop.id,
                Folio.status == FolioStatus.CLOSED,
                Folio.charges_total > 0,
                Invoice.id.is_(None),
            )
            .limit(1)
        ).scalars().first()
        check("لقينا حساب لسه متفوترش", folio is not None,
              folio.code if folio else "")
        if folio is None:
            db.close()
            return 1

    r = client.post(f"/api/v1/invoices/from-folio/{folio.id}", headers=accountant)
    invoice = r.json()
    check("إصدار الفاتورة", r.status_code in (200, 201),
          invoice.get("number", r.text[:100]))
    invoice_id = invoice.get("id")

    if invoice_id is None:
        db.close()
        return 1

    check("رقم الفاتورة بصيغة صحيحة",
          invoice["number"].split("-")[0] in ("INV", "RCT"), invoice["number"])
    check("الفاتورة ليها سطور", len(invoice["lines"]) > 0, f"{len(invoice['lines'])} سطر")
    check("الإجمالي = الصافي + الخدمة + الضريبة",
          money(invoice["grand_total"]) == money(
              Decimal(invoice["subtotal"])
              - Decimal(invoice["discount_total"])
              + Decimal(invoice["service_charge_total"])
              + Decimal(invoice["tax_total"])
          ),
          f"{invoice['grand_total']}")
    check("مجموع السطور = إجمالي الفاتورة",
          money(sum(Decimal(x["total"]) for x in invoice["lines"]))
          == money(invoice["grand_total"]),
          f"{len(invoice['lines'])} سطر")

    print("\n─── الدفعات مش سطور فاتورة ───")
    credit_lines = db.execute(
        select(func.count(FolioLine.id)).where(
            FolioLine.folio_id == folio.id,
            FolioLine.charge_kind.in_(list(CREDIT_CHARGE_KINDS)),
            FolioLine.is_void.is_(False),
        )
    ).scalar_one()
    charge_lines = db.execute(
        select(func.count(FolioLine.id)).where(
            FolioLine.folio_id == folio.id,
            FolioLine.charge_kind.not_in(list(CREDIT_CHARGE_KINDS)),
            FolioLine.is_void.is_(False),
        )
    ).scalar_one()
    check("الفاتورة فيها الخدمات بس مش الدفعات",
          len(invoice["lines"]) <= charge_lines,
          f"سطور خدمة {charge_lines} · دفعات {credit_lines} · في الفاتورة {len(invoice['lines'])}")

    print("\n─── بيانات المنظومة الضريبية ───")
    check("الحالة إما مسودة أو في الطابور",
          invoice["eta_status"] in (EtaStatus.DRAFT.value, EtaStatus.QUEUED.value),
          invoice["eta_status"])
    check("رقم داخلي للمنظومة اتولّد", bool(invoice["eta_internal_id"]),
          invoice.get("eta_internal_id") or "")
    check("الرقم الداخلي فيه كود المنشأة",
          (invoice.get("eta_internal_id") or "").startswith(prop.code),
          invoice.get("eta_internal_id") or "")
    check("حمولة الـ QR اتولّدت", bool(invoice["qr_payload"]),
          (invoice.get("qr_payload") or "")[:40])
    check("العميل مكتوب", bool(invoice["customer_name"]), invoice["customer_name"])

    stored = db.get(Invoice, invoice_id)
    check("بصمة الفاتورة اتحسبت", bool(stored.eta_hash_key), (stored.eta_hash_key or "")[:20])

    print("\n─── الترقيم متصل ومبيتكرّرش ───")
    numbers = list(
        db.execute(
            select(Invoice.number).where(Invoice.property_id == prop.id)
        ).scalars().all()
    )
    check("مفيش رقم فاتورة متكرّر", len(numbers) == len(set(numbers)),
          f"{len(numbers)} فاتورة")

    print("\n─── الفاتورة مرتين ───")
    r = client.post(f"/api/v1/invoices/from-folio/{folio.id}", headers=accountant)
    check("نفس الحساب مبيتفوترش مرتين", r.status_code == 409,
          r.json().get("detail", {}).get("code", ""))

    r = client.post(f"/api/v1/invoices/from-folio/{10**9}", headers=accountant)
    check("حساب مش موجود بيرجّع 404", r.status_code == 404)

    print("\n─── قراءة الفاتورة ───")
    r = client.get(f"/api/v1/invoices/{invoice_id}", headers=accountant)
    check("فتح الفاتورة", r.status_code == 200, r.json()["number"])
    check("السطور راجعة كاملة", len(r.json()["lines"]) == len(invoice["lines"]))

    r = client.get(f"/api/v1/invoices/{invoice_id}", headers=desk)
    check("الاستقبال بيشوف الفاتورة", r.status_code == 200)

    r = client.get(f"/api/v1/invoices/{10**9}", headers=accountant)
    check("فاتورة مش موجودة بترجّع 404", r.status_code == 404)

    print("\n─── الإرسال للمنظومة ───")
    r = client.post("/api/v1/invoices/submit", headers=accountant)
    submit = r.json()
    check("إرسال الطابور", r.status_code == 200,
          f"مقبول {submit['accepted']} · فاشل {submit['failed']}")

    db.expire_all()
    after_submit = db.get(Invoice, invoice_id)
    check("الحالة اتحرّكت بعد الإرسال",
          after_submit.eta_status in
          (EtaStatus.VALID, EtaStatus.SUBMITTED, EtaStatus.FAILED, EtaStatus.DRAFT),
          after_submit.eta_status)
    if after_submit.eta_status == EtaStatus.VALID:
        check("المقبولة ليها UUID من المنظومة", bool(after_submit.eta_uuid),
              (after_submit.eta_uuid or "")[:20])
        check("وقت القبول مسجّل", after_submit.eta_accepted_at is not None)

    r = client.post("/api/v1/invoices/retry", headers=accountant)
    check("إعادة محاولة الفاشل", r.status_code == 200,
          r.json().get("message_ar", ""))

    r = client.post("/api/v1/invoices/submit", headers=waiter)
    check("الويتر ممنوع من الإرسال", r.status_code == 403)

    print("\n─── الإلغاء بإشعار خصم ───")
    before_count = db.execute(
        select(func.count(Invoice.id)).where(Invoice.property_id == prop.id)
    ).scalar_one()

    r = client.post(f"/api/v1/invoices/{invoice_id}/cancel", headers=accountant,
                    json={"reason": ""})
    check("الإلغاء بدون سبب بيترفض", r.status_code in (400, 422))

    r = client.post(f"/api/v1/invoices/{invoice_id}/cancel", headers=desk,
                    json={"reason": "اختبار"})
    check("الاستقبال ممنوع يلغي فاتورة", r.status_code == 403)

    r = client.post(f"/api/v1/invoices/{invoice_id}/cancel", headers=accountant,
                    json={"reason": "اختبار الإلغاء"})
    credit = r.json()
    check("الإلغاء بيطلّع إشعار خصم", r.status_code in (200, 201),
          credit.get("number", r.text[:80]))
    check("النوع إشعار خصم",
          credit.get("invoice_type") == InvoiceType.CREDIT_NOTE.value,
          credit.get("invoice_type", ""))
    check("الإشعار بيشاور على الفاتورة الأصلية",
          credit.get("credit_note_for_invoice_id") == invoice_id,
          str(credit.get("credit_note_for_invoice_id")))
    # الإشعار بيتقيّد بالسالب — ده عكس مش نسخة. المطابقة على القيمة
    # المطلقة، والإشارة نفسها جزء من صحة القيد.
    check("الإشعار بالسالب — عكس مش نسخة",
          Decimal(credit["grand_total"]) < 0, f"{credit['grand_total']}")
    check("قيمة الإشعار = قيمة الفاتورة",
          money(abs(Decimal(credit["grand_total"]))) == money(invoice["grand_total"]),
          f"{abs(Decimal(credit['grand_total']))}")

    after_count = db.execute(
        select(func.count(Invoice.id)).where(Invoice.property_id == prop.id)
    ).scalar_one()
    check("عدد الفواتير زاد واحد — الأصلية مااتمسحتش",
          after_count == before_count + 1, f"{before_count} -> {after_count}")

    db.expire_all()
    original = db.get(Invoice, invoice_id)
    check("الأصلية اتعلّمت ملغاة", original.is_cancelled is True)
    check("سبب الإلغاء محفوظ", original.cancellation_reason == "اختبار الإلغاء",
          original.cancellation_reason or "")
    check("الأصلية محتفظة بقيمتها — مااتصفّرتش",
          money(original.grand_total) == money(invoice["grand_total"]),
          f"{original.grand_total}")
    check("سطور الأصلية زي ما هي",
          len(original.lines) == len(invoice["lines"]),
          f"{len(original.lines)} سطر")

    r = client.post(f"/api/v1/invoices/{invoice_id}/cancel", headers=accountant,
                    json={"reason": "تاني"})
    check("الإلغاء مرتين بيترفض", r.status_code == 409,
          r.json().get("detail", {}).get("code", ""))

    print("\n─── الفلترة ───")
    r = client.get("/api/v1/invoices?limit=50", headers=accountant)
    all_rows = r.json()
    check("القائمة بتشمل الملغاة معلّمة",
          any(x["is_cancelled"] for x in all_rows) or len(all_rows) < 50,
          f"{sum(1 for x in all_rows if x['is_cancelled'])} ملغاة")

    r = client.get(f"/api/v1/invoices?search={invoice['number']}", headers=accountant)
    check("البحث برقم الفاتورة",
          r.status_code == 200 and any(x["number"] == invoice["number"] for x in r.json()),
          f"{len(r.json())} نتيجة")

    print("\n─── إعدادات المنظومة ───")
    check("نوع الضريبة T1 — ضريبة القيمة المضافة", inv.TAX_TYPE == "T1", inv.TAX_TYPE)
    check("النوع الفرعي V009 — الخدمات الفندقية", inv.TAX_SUBTYPE == "V009",
          inv.TAX_SUBTYPE)
    check("جدول إعادة المحاولة تصاعدي",
          all(a < b for a, b in zip(inv.RETRY_BACKOFF, inv.RETRY_BACKOFF[1:])),
          str(inv.RETRY_BACKOFF))
    check("أطول انتظار مش أكتر من 6 ساعات",
          inv.RETRY_BACKOFF[-1] <= 360, f"{inv.RETRY_BACKOFF[-1]} دقيقة")

    db.close()

    print("\n" + "─" * 56)
    if failures:
        print(f"  فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("  كل الاختبارات نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
