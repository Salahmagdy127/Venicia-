"""اختبار المحاسبة والمرتبات — Accounting and payroll flow test.

    python -m scripts.test_accounting_flow

بيغطّي: دليل الحسابات · قواعد الترحيل · التوازن · العكس · القوائم ·
إقفال الفترة · حساب الضريبة والتأمينات · المسيّر وترحيله · والاختبار
اللي بيثبت الربط: المخزون في الميزانية = المخزون في المخازن.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import SessionLocal
from app.main import app
from app.models.accounting import Account, JournalEntry
from app.models.enums import JournalSource, MovementKind, PayrollStatus
from app.models.folio import FolioLine, Payment
from app.models.organization import Property
from app.models.stock import StockMovement
from app.services import accounting as gl
from app.services import gl_posting as posting
from app.services import payroll as pr
from app.services import stock as stock_svc

PASS, FAIL = "  [OK]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{PASS if ok else FAIL} {label}" + (f"  ->  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def main() -> int:  # noqa: PLR0915 — اختبار تدفّق، الطول مقصود
    client = TestClient(app)
    db = SessionLocal()

    def login(username: str) -> dict:
        r = client.post(
            "/api/v1/auth/login", data={"username": username, "password": "venicia2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    owner = login("owner")
    accountant = login("hesham")   # محاسب — بيرحّل ويقفل
    hr_manager = login("nadia")    # شؤون عاملين — مفيش دخول على الدفتر
    cashier = login("sayed")

    prop = db.execute(select(Property).where(Property.code == "VNC")).scalar_one()
    today = date.today()

    print("\n─── دليل الحسابات ───")
    r = client.get("/api/v1/accounting/chart", headers=accountant)
    chart = r.json()
    check("دليل الحسابات", r.status_code == 200 and len(chart) >= 50, f"{len(chart)} حساب")

    by_code = {a["code"]: a for a in chart}
    check("الحسابات الأساسية موجودة",
          all(c in by_code for c in ("1110", "1210", "1310", "2110", "2210", "4110", "5110")))
    check("الحساب التجميعي مش قابل للترحيل", by_code["1"]["is_postable"] is False)
    check("الحساب الطرفي قابل للترحيل", by_code["1110"]["is_postable"] is True)

    types = {a["account_type"] for a in chart}
    check("الأنواع الخمسة كلها ممثّلة", types == {
        "ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"
    }, str(sorted(types)))

    r = client.get("/api/v1/accounting/cost-centers", headers=accountant)
    centers = r.json()
    check("مراكز التكلفة", r.status_code == 200 and len(centers) >= 5, f"{len(centers)} مركز")

    print("\n─── قواعد الترحيل ───")
    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "قيد مش متوازن",
        "lines": [
            {"account_code": "1110", "debit": "1000"},
            {"account_code": "4490", "credit": "900"},
        ],
    })
    check("القيد المش متوازن بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("code", ""))

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "ترحيل على حساب تجميعي",
        "lines": [
            {"account_code": "1", "debit": "500"},
            {"account_code": "4490", "credit": "500"},
        ],
    })
    check("الترحيل على حساب تجميعي بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("code", ""))

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "حساب مش موجود",
        "lines": [
            {"account_code": "9999", "debit": "500"},
            {"account_code": "4490", "credit": "500"},
        ],
    })
    check("الحساب المش موجود بيترفض", r.status_code == 404)

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "سطر مدين ودائن مع بعض",
        "lines": [
            {"account_code": "1110", "debit": "500", "credit": "500"},
            {"account_code": "4490", "credit": "500"},
        ],
    })
    check("السطر المدين والدائن مع بعض بيترفض", r.status_code == 400,
          r.json().get("detail", {}).get("code", ""))

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "قيمة بالسالب",
        "lines": [
            {"account_code": "1110", "debit": "-500"},
            {"account_code": "4490", "credit": "-500"},
        ],
    })
    check("القيمة السالبة بترفض", r.status_code == 400,
          r.json().get("detail", {}).get("code", ""))

    print("\n─── قيد يدوي صحيح ───")
    before_cash = gl.get_account(db, prop.id, "1110").balance
    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(today),
        "description_ar": "إيراد متنوع نقدي — اختبار",
        "lines": [
            {"account_code": "1110", "debit": "2500", "description_ar": "تحصيل نقدي"},
            {"account_code": "4490", "credit": "2500", "cost_center_code": "ADMIN"},
        ],
    })
    entry = r.json()
    check("القيد المتوازن بيتقبل", r.status_code == 201, entry.get("number", ""))
    check("رقم القيد بصيغة صحيحة", entry["number"].startswith("JV-"), entry["number"])
    check("المدين = الدائن", entry["total_debit"] == entry["total_credit"],
          f"{entry['total_debit']}")
    check("القيد فيه سطرين", len(entry["lines"]) == 2)

    db.expire_all()
    after_cash = gl.get_account(db, prop.id, "1110").balance
    check("رصيد الخزينة اتحرّك بالمبلغ", after_cash - before_cash == Decimal("2500"),
          f"{before_cash} -> {after_cash}")

    print("\n─── العكس ───")
    r = client.post(f"/api/v1/accounting/journal/{entry['id']}/reverse",
                    headers=accountant, json={"reason": ""})
    check("العكس بدون سبب بيترفض", r.status_code == 400)

    r = client.post(f"/api/v1/accounting/journal/{entry['id']}/reverse",
                    headers=accountant, json={"reason": "اختبار العكس"})
    reversal = r.json()
    check("العكس بيتقبل بسبب", r.status_code == 200, reversal.get("number", ""))
    check("القيد المضاد بيشاور على الأصلي", reversal["reverses_entry_id"] == entry["id"])

    original_line = entry["lines"][0]
    mirror = next(x for x in reversal["lines"] if x["account_code"] == original_line["account_code"])
    check("الاتجاه اتقلب", mirror["credit"] == original_line["debit"],
          f"{original_line['debit']} مدين -> {mirror['credit']} دائن")

    db.expire_all()
    check("الرصيد رجع زي ما كان",
          gl.get_account(db, prop.id, "1110").balance == before_cash,
          f"{gl.get_account(db, prop.id, '1110').balance}")

    r = client.post(f"/api/v1/accounting/journal/{entry['id']}/reverse",
                    headers=accountant, json={"reason": "تاني"})
    check("العكس مرتين بيترفض", r.status_code == 409)

    original = db.get(JournalEntry, entry["id"])
    db.refresh(original)
    check("القيد الأصلي فضل مكانه بحالة REVERSED", original.status == "REVERSED",
          original.status)

    print("\n─── الترحيل التلقائي ───")
    day = _busiest_day(db, prop.id)
    check("فيه يوم فيه حركة", day is not None, str(day))

    existing = db.execute(
        select(JournalEntry).where(
            JournalEntry.property_id == prop.id,
            JournalEntry.business_date == day,
            JournalEntry.source == JournalSource.ROOM_REVENUE,
        )
    ).scalar_one_or_none()
    check("اليوم مرحّل أصلاً من بناء الدفتر", existing is not None,
          existing.number if existing else "")

    result = posting.post_day(db, prop.id, day)
    db.commit()
    check("إعادة الترحيل مبتكرّرش", result.posted == 0,
          f"{result.posted} قيد جديد · اتخطّى {len(result.skipped)}")

    r = client.post("/api/v1/accounting/post-day", headers=accountant,
                    json={"business_date": str(today + timedelta(days=3))})
    check("ترحيل يوم في المستقبل بيترفض", r.status_code == 422)

    print("\n─── التوازن على مستوى الدفتر ───")
    r = client.get("/api/v1/accounting/trial-balance", headers=accountant)
    trial = r.json()
    check("ميزان المراجعة", r.status_code == 200 and len(trial["rows"]) > 10,
          f"{len(trial['rows'])} حساب")
    check("الميزان متوازن", trial["is_balanced"] is True, f"فرق {trial['difference']}")
    check("المدين = الدائن", trial["total_debit"] == trial["total_credit"],
          f"{money(trial['total_debit']):,}")

    r = client.get(f"/api/v1/accounting/balance-sheet?as_of={today}", headers=accountant)
    sheet = r.json()
    check("المركز المالي", r.status_code == 200)
    check("الأصول = الالتزامات + حقوق الملكية + الربح", sheet["is_balanced"] is True,
          f"فرق {sheet['difference']}")
    check("الأصول موجبة", Decimal(sheet["total_assets"]) > 0,
          f"{money(sheet['total_assets']):,}")

    go_live = date(2026, 8, 1)
    r = client.get(
        f"/api/v1/accounting/income-statement?since={go_live}&until={today}",
        headers=accountant,
    )
    income = r.json()
    check("قائمة الدخل", r.status_code == 200)
    check("فيه إيراد", Decimal(income["total_revenue"]) > 0,
          f"{money(income['total_revenue']):,}")
    check("فيه مصروف", Decimal(income["total_expenses"]) > 0,
          f"{money(income['total_expenses']):,}")
    check("الربح = الإيراد − المصروف",
          money(income["net_profit"])
          == money(Decimal(income["total_revenue"]) - Decimal(income["total_expenses"])))
    check("الهامش منطقي (بين 10% و70%)",
          Decimal("10") < Decimal(income["margin_percent"]) < Decimal("70"),
          f"{income['margin_percent']}%")

    codes = {r["code"] for r in income["revenue"]}
    check("إيراد الإقامة موجود", "4110" in codes)
    expense_codes = {r["code"] for r in income["expenses"]}
    check("تكلفة المبيعات موجودة", "5110" in expense_codes)
    check("المرتبات موجودة", "5210" in expense_codes)

    r = client.get(
        f"/api/v1/accounting/income-statement?since={today}&until={go_live}",
        headers=accountant,
    )
    check("المدى المقلوب بيترفض", r.status_code == 422)

    r = client.get(
        f"/api/v1/accounting/income-statement?since={today - timedelta(days=900)}"
        f"&until={today}",
        headers=accountant,
    )
    check("المدى الأكبر من سنتين بيترفض", r.status_code == 422)

    print("\n─── الربط بالمخزن ───")
    # إعادة ترحيل النهارده: سويتات الكاشير صرفت من المخزن بعد ما اليوم
    # كان اترحّل، فالحركة الجديدة برّه الدفتر. إعادة الترحيل بتعكس
    # القيود التلقائية وتبنيها من الأول — وده اللي بيخلّي الرقمين يطابقوا.
    before = len(gl.journal(db, prop.id, since=today, until=today, limit=200))
    reposted = posting.repost_day(db, prop.id, today)
    db.commit()
    db.expire_all()
    check("إعادة ترحيل يوم بترحّل من الأول", reposted.posted > 0,
          f"{reposted.posted} قيد جديد")
    after = len(gl.journal(db, prop.id, since=today, until=today, limit=200))
    check("العكس والترحيل الجديد الاتنين اتسجّلوا", after > before,
          f"{before} -> {after} قيد")
    check("الميزان لسه متوازن بعد إعادة الترحيل",
          gl.trial_balance(db, prop.id).is_balanced)

    book = gl.get_account(db, prop.id, "1310").balance
    supplies = gl.get_account(db, prop.id, "1320").balance
    real = next(
        (v.value for v in stock_svc.valuation(db, prop.id) if v.warehouse_id is None),
        Decimal("0"),
    )
    check("المخزون في الميزانية = المخزون في المخازن",
          money(book + supplies) == money(real),
          f"دفتر {money(book + supplies):,} · مخازن {money(real):,}")
    reval = db.execute(
        select(JournalEntry).where(
            JournalEntry.property_id == prop.id,
            JournalEntry.source_key == f"REVAL:{today}",
        )
    ).scalar_one_or_none()
    check("فرق التقييم بيترحّل بقيد مش بيتسكت عنه",
          reval is None or reval.total_debit > 0,
          reval.number if reval else "مفيش فرق")

    print("\n─── كشف الأستاذ ───")
    cash_account = db.execute(
        select(Account).where(Account.property_id == prop.id, Account.code == "1110")
    ).scalar_one()
    r = client.get(f"/api/v1/accounting/ledger/{cash_account.id}", headers=accountant)
    ledger = r.json()
    check("كشف حساب الخزينة", r.status_code == 200 and len(ledger["rows"]) > 0,
          f"{len(ledger['rows'])} حركة")
    if ledger["rows"]:
        last_row = ledger["rows"][-1]
        check("الرصيد المتحرّك بيوصل لرصيد الحساب",
              money(last_row["running_balance"]) == money(ledger["account"]["balance"]),
              f"{money(last_row['running_balance']):,}")

    r = client.get("/api/v1/accounting/journal?limit=20", headers=accountant)
    journal = r.json()
    check("دفتر اليومية", r.status_code == 200 and len(journal) > 0, f"{len(journal)} قيد")
    check("كل قيد متوازن",
          all(j["total_debit"] == j["total_credit"] for j in journal))

    r = client.get(
        f"/api/v1/accounting/journal?source={JournalSource.ROOM_REVENUE.value}",
        headers=accountant,
    )
    check("الفلترة بالمصدر",
          r.status_code == 200 and all(j["source"] == "ROOM_REVENUE" for j in r.json()),
          f"{len(r.json())} قيد إيراد إقامة")

    print("\n─── اللوحة والصلاحيات ───")
    r = client.get("/api/v1/accounting", headers=accountant)
    board = r.json()
    check("لوحة الحسابات", r.status_code == 200)
    check("اللوحة بتقول الدفتر متوازن", board["is_balanced"] is True)
    check("قيمة المخزون في اللوحة = المخازن",
          money(board["inventory_value"]) == money(real),
          f"{money(board['inventory_value']):,}")
    check("ربح الشهر = إيراد − مصروف",
          money(board["month_profit"])
          == money(Decimal(board["month_revenue"]) - Decimal(board["month_expenses"])))

    r = client.get("/api/v1/accounting", headers=cashier)
    check("الكاشير ممنوع من الحسابات", r.status_code == 403)
    r = client.post("/api/v1/accounting/journal", headers=cashier, json={
        "business_date": str(today), "description_ar": "x",
        "lines": [{"account_code": "1110", "debit": "1"}],
    })
    check("الكاشير ممنوع من الترحيل", r.status_code == 403)

    print("\n─── إقفال الفترة ───")
    old = today - timedelta(days=400)
    r = client.post(
        f"/api/v1/accounting/periods/{old.year}/{old.month}/close", headers=owner
    )
    check("إقفال شهر قديم", r.status_code == 200, r.json().get("status", ""))

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(old),
        "description_ar": "ترحيل في شهر مقفول",
        "lines": [
            {"account_code": "1110", "debit": "100"},
            {"account_code": "4490", "credit": "100"},
        ],
    })
    check("الترحيل في شهر مقفول بيترفض", r.status_code == 409,
          r.json().get("detail", {}).get("code", ""))

    r = client.post(
        f"/api/v1/accounting/periods/{old.year}/{old.month}/reopen",
        headers=owner, json={"reason": ""},
    )
    check("إعادة الفتح بدون سبب بترفض", r.status_code == 400)

    r = client.post(
        f"/api/v1/accounting/periods/{old.year}/{old.month}/reopen",
        headers=owner, json={"reason": "تصحيح قيد ناقص"},
    )
    check("إعادة الفتح بسبب", r.status_code == 200 and r.json()["status"] == "OPEN")

    r = client.post("/api/v1/accounting/journal", headers=accountant, json={
        "business_date": str(old),
        "description_ar": "الشهر اتفتح تاني — اختبار",
        "lines": [
            {"account_code": "1110", "debit": "100"},
            {"account_code": "4490", "credit": "100"},
        ],
    })
    check("الترحيل بيشتغل بعد إعادة الفتح", r.status_code == 201)
    if r.status_code == 201:
        client.post(f"/api/v1/accounting/journal/{r.json()['id']}/reverse",
                    headers=accountant, json={"reason": "تنضيف بعد الاختبار"})

    print("\n─── حساب الضريبة والتأمينات ───")
    check("المرتب تحت الإعفاء ضريبته صفر",
          pr.annual_income_tax(Decimal("50000")) == Decimal("0"),
          "50,000 سنوي")
    # 60,000 سنوي: 20,000 إعفاء -> 40,000 وعاء -> أول 40,000 بصفر
    check("الوعاء لحد 40 ألف بصفر",
          pr.annual_income_tax(Decimal("60000")) == Decimal("0"),
          "60,000 سنوي")
    # 100,000: وعاء 80,000 -> 40k×0 + 15k×10% + 15k×15% + 10k×20% = 5,750
    check("الشرايح تصاعدية مش نسبة واحدة",
          pr.annual_income_tax(Decimal("100000")) == Decimal("5750.00"),
          f"{pr.annual_income_tax(Decimal('100000'))}")
    check("الضريبة بتزيد مع الدخل",
          pr.annual_income_tax(Decimal("500000")) > pr.annual_income_tax(Decimal("300000")))
    check("النسبة الفعلية أقل من أعلى شريحة",
          pr.annual_income_tax(Decimal("500000")) / Decimal("500000") * 100
          < Decimal("27.5"),
          f"{pr.annual_income_tax(Decimal('500000')) / 5000:.2f}%")

    class _Fake:
        is_insured = True
        insurance_salary = Decimal("50000")
        basic_salary = Decimal("50000")

    check("الأجر التأميني بيتقصّ على الحد الأقصى",
          pr.insurance_base(_Fake()) == pr.INSURANCE_SALARY_MAX,
          f"{pr.insurance_base(_Fake())}")

    _Fake.insurance_salary = Decimal("1000")
    _Fake.basic_salary = Decimal("1000")
    check("الأجر التأميني بيترفع للحد الأدنى",
          pr.insurance_base(_Fake()) == pr.INSURANCE_SALARY_MIN,
          f"{pr.insurance_base(_Fake())}")

    _Fake.is_insured = False
    check("غير المؤمّن عليه اشتراكه صفر", pr.insurance_base(_Fake()) == Decimal("0"))

    r = client.get("/api/v1/hr/tax-preview?monthly_gross=20000", headers=owner)
    preview = r.json()
    check("معاينة الضريبة", r.status_code == 200)
    check("الضريبة الشهرية = السنوية ÷ 12",
          money(preview["monthly_tax"]) == money(Decimal(preview["annual_tax"]) / 12),
          f"{preview['monthly_tax']} شهري")

    print("\n─── العاملون ───")
    r = client.get("/api/v1/hr", headers=owner)
    staff = r.json()
    check("لوحة العاملين", r.status_code == 200 and staff["headcount"] > 50,
          f"{staff['headcount']} موظف")
    check("الأقسام", len(staff["departments"]) >= 8, f"{len(staff['departments'])} قسم")
    check("مجموع عدد الأقسام = العدد الكلي",
          sum(d["headcount"] for d in staff["departments"]) == staff["headcount"])
    check("تكلفة المرتبات الشهرية", Decimal(staff["monthly_payroll_cost"]) > 0,
          f"{money(staff['monthly_payroll_cost']):,}")

    r = client.get("/api/v1/hr", headers=cashier)
    check("الكاشير ممنوع من بيانات العاملين", r.status_code == 403)

    department = staff["departments"][0]
    r = client.get(f"/api/v1/hr?department_id={department['id']}", headers=owner)
    check("الفلترة بالقسم",
          r.status_code == 200
          and all(e["department_id"] == department["id"] for e in r.json()["employees"]),
          f"{len(r.json()['employees'])} موظف في {department['name_ar']}")

    print("\n─── المسيّر ───")
    r = client.get("/api/v1/hr/payroll", headers=owner)
    runs = r.json()
    check("قايمة المسيّرات", r.status_code == 200 and len(runs) > 0, f"{len(runs)} مسيّر")

    current = next((x for x in runs if x["year"] == today.year and x["month"] == today.month), None)
    check("مسيّر الشهر الحالي موجود", current is not None)

    if current:
        r = client.get(f"/api/v1/hr/payroll/{current['id']}", headers=owner)
        detail = r.json()
        check("تفاصيل المسيّر", r.status_code == 200)
        check("عدد القسايم = عدد الموظفين",
              len(detail["payslips"]) == detail["headcount"],
              f"{len(detail['payslips'])} قسيمة")

        slips = detail["payslips"]
        check("الإجمالي = أساسي + بدلات + خدمة + إضافي + مكافأة",
              all(
                  money(s["gross"]) == money(
                      Decimal(s["basic_salary"]) + Decimal(s["allowances"])
                      + Decimal(s["overtime"]) + Decimal(s["service_share"])
                      + Decimal(s["bonus"])
                  )
                  for s in slips
              ))
        check("الصافي = الإجمالي − الاستقطاعات",
              all(
                  money(s["net_pay"]) == money(
                      Decimal(s["gross"]) - Decimal(s["total_deductions"])
                  )
                  for s in slips
              ))
        check("مفيش صافي بالسالب", all(Decimal(s["net_pay"]) > 0 for s in slips))
        check("مجموع القسايم = إجمالي المسيّر",
              money(sum(Decimal(s["gross"]) for s in slips)) == money(detail["total_gross"]),
              f"{money(detail['total_gross']):,}")

        check("الخدمة اتوزّعت بالكامل",
              money(sum(Decimal(s["service_share"]) for s in slips))
              == money(detail["service_pool"]),
              f"حوض {money(detail['service_pool']):,}")
        check("حوض الخدمة اتحسب من الدفتر مش تقدير",
              Decimal(detail["service_pool"]) > 0,
              f"{money(detail['service_pool']):,}")

        highest = max(slips, key=lambda s: Decimal(s["gross"]))
        lowest = min(slips, key=lambda s: Decimal(s["gross"]))
        check("الأعلى أجراً بياخد خدمة أكبر",
              Decimal(highest["service_share"]) >= Decimal(lowest["service_share"]),
              f"{highest['job_title_ar']} مقابل {lowest['job_title_ar']}")

        check("التكلفة على المنشأة = الإجمالي + حصة صاحب العمل",
              money(detail["total_cost"]) == money(
                  Decimal(detail["total_gross"])
                  + Decimal(detail["total_insurance_employer"])
              ),
              f"{money(detail['total_cost']):,}")
        check("توزيع التكلفة على الأقسام",
              len(detail["by_department"]) >= 5,
              f"{len(detail['by_department'])} قسم")
        check("مجموع تكلفة الأقسام = تكلفة المسيّر",
              money(sum(Decimal(d["employer_cost"]) for d in detail["by_department"]))
              == money(detail["total_cost"]))

        check("المسيّر معتمد", detail["status"] == PayrollStatus.APPROVED.value,
              detail["status"])
        check("المسيّر مربوط بقيد في الدفتر", detail["journal_entry_id"] is not None,
              str(detail["journal_entry_id"]))

        posted = db.get(JournalEntry, detail["journal_entry_id"])
        check("قيد المسيّر متوازن", posted.total_debit == posted.total_credit,
              f"{money(posted.total_debit):,}")
        check("قيد المسيّر مصدره PAYROLL", posted.source == JournalSource.PAYROLL)
        accounts = {
            db.get(Account, x.account_id).code for x in posted.lines
        }
        check("القيد بيحرّك حسابات المرتبات والتأمينات والضريبة",
              {"5210", "2410", "2420", "2430"} <= accounts,
              str(sorted(accounts)))
        check("القيد بيخفّض التزام الخدمة", "2230" in accounts)

        r = client.post("/api/v1/hr/payroll/build", headers=owner,
                        json={"year": today.year, "month": today.month})
        check("إعادة حساب مسيّر معتمد بترفض", r.status_code == 409,
              r.json().get("detail", {}).get("code", ""))

        r = client.post(f"/api/v1/hr/payroll/{current['id']}/approve", headers=owner)
        check("اعتماد مسيّر معتمد بيترفض", r.status_code == 409)

    r = client.post("/api/v1/hr/payroll/build", headers=owner,
                    json={"year": today.year, "month": 13})
    check("الشهر الغلط بيترفض", r.status_code == 400)

    r = client.post("/api/v1/hr/payroll/build", headers=cashier,
                    json={"year": today.year, "month": today.month})
    check("الكاشير ممنوع من المسيّر", r.status_code == 403)

    print("\n─── سلامة الدفتر بعد كل ده ───")
    db.expire_all()
    final = gl.trial_balance(db, prop.id)
    check("الميزان لسه متوازن", final.is_balanced, f"فرق {final.difference}")

    rebuilt = gl.rebuild_balances(db, prop.id)
    db.commit()
    check("إعادة بناء الأرصدة من القيود", rebuilt > 0, f"{rebuilt} حساب")

    after_rebuild = gl.trial_balance(db, prop.id)
    check("الميزان بعد إعادة البناء زي ما هو",
          after_rebuild.total_debit == final.total_debit
          and after_rebuild.total_credit == final.total_credit,
          f"{money(after_rebuild.total_debit):,}")

    sheet_after = gl.balance_sheet(db, prop.id, today)
    check("المركز المالي لسه متوازن بعد إعادة البناء", sheet_after.is_balanced,
          f"فرق {sheet_after.difference}")

    db.close()

    print("\n" + "─" * 56)
    if failures:
        print(f"  فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("  كل الاختبارات نجحت")
    return 0


def _has_user(db, username: str) -> bool:
    from app.models.security import User

    return db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none() is not None


def _busiest_day(db, property_id: int):
    from sqlalchemy import func

    row = db.execute(
        select(FolioLine.business_date, func.count(FolioLine.id))
        .where(
            FolioLine.property_id == property_id,
            FolioLine.business_date >= date(2026, 8, 1),
        )
        .group_by(FolioLine.business_date)
        .order_by(func.count(FolioLine.id).desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    day = row[0]
    return date.fromisoformat(day[:10]) if isinstance(day, str) else day


if __name__ == "__main__":
    raise SystemExit(main())
