"""المنيو العام بالـ QR — Public QR menu.

النزيل بيمسح الكود من على الطاولة ويشوف المنيو على موبايله. المسارات دي
**مفتوحة من غير تسجيل دخول** زي صفحة الحجز، وعشان كده متقشّرة: الأصناف
وأسعارها وبس. مفيش تكلفة ولا هامش ربح ولا أي رقم داخلي.

الأصناف اللي خلصت بتتشال من العرض فوراً — النزيل مايطلبش حاجة مش موجودة
ويتقاله بعدين «معلش خلصت».
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import segno
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProperty, CurrentUser, DbSession, require
from app.models.organization import Property
from app.models.pos import MenuCategory, MenuItem, Outlet, PosTable
from app.schemas.common import ApiModel

router = APIRouter(tags=["منيو الـ QR — Public menu"])


class PublicMenuItem(ApiModel):
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    price: Decimal
    is_vegetarian: bool
    contains_alcohol: bool
    preparation_minutes: int | None = None
    #: خلص دلوقتي — بيتعرض رمادي بدل ما يتشال، عشان النزيل يعرف إنه موجود عادةً
    is_out_of_stock: bool


class PublicMenuCategory(ApiModel):
    name_ar: str
    name_en: str
    items: list[PublicMenuItem]


class PublicMenu(ApiModel):
    property_name_ar: str
    property_name_en: str
    outlet_code: str
    outlet_name_ar: str
    outlet_name_en: str
    outlet_type: str
    currency: str
    service_charge_percent: Decimal
    vat_percent: Decimal
    table_label: str | None = None
    categories: list[PublicMenuCategory]
    item_count: int


def _outlet_or_404(db, code: str) -> tuple[Property, Outlet]:
    outlet = db.execute(
        select(Outlet).where(Outlet.code == code.upper(), Outlet.is_active.is_(True))
    ).scalar_one_or_none()
    if outlet is None:
        raise HTTPException(
            status_code=404,
            detail={"ar": "المنفذ ده مش موجود", "en": "Outlet not found"},
        )
    prop = db.get(Property, outlet.property_id)
    return prop, outlet


@router.get("/menu/{outlet_code}", response_model=PublicMenu, summary="منيو المنفذ للزوار")
def public_menu(
    outlet_code: str,
    db: DbSession,
    table: str | None = None,
) -> PublicMenu:
    """المنيو زي ما النزيل بيشوفه على موبايله.

    ``table`` بييجي من الكود المطبوع على الطاولة — بيتعرض بس، عشان النزيل
    يتأكد إنه مسح كود طاولته صح.
    """
    prop, outlet = _outlet_or_404(db, outlet_code)

    categories = list(
        db.execute(
            select(MenuCategory)
            .where(MenuCategory.property_id == prop.id, MenuCategory.is_active.is_(True))
            .order_by(MenuCategory.sort_order, MenuCategory.id)
        ).scalars().all()
    )

    items = list(
        db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.outlets))
            .where(
                MenuItem.property_id == prop.id,
                MenuItem.is_active.is_(True),
                MenuItem.is_available.is_(True),
            )
            .order_by(MenuItem.sort_order, MenuItem.id)
        ).scalars().unique().all()
    )
    mine = [i for i in items if any(o.id == outlet.id for o in i.outlets)]

    table_label = None
    if table:
        row = db.execute(
            select(PosTable).where(
                PosTable.outlet_id == outlet.id, PosTable.label == table.strip()
            ).limit(1)
        ).scalar_one_or_none()
        table_label = row.label if row else None

    groups: list[PublicMenuCategory] = []
    for category in categories:
        rows = [i for i in mine if i.category_id == category.id]
        if not rows:
            continue
        groups.append(
            PublicMenuCategory(
                name_ar=category.name_ar,
                name_en=category.name_en,
                items=[
                    PublicMenuItem(
                        name_ar=i.name_ar,
                        name_en=i.name_en,
                        description_ar=i.description_ar,
                        description_en=i.description_en,
                        price=i.price,
                        is_vegetarian=i.is_vegetarian,
                        contains_alcohol=i.contains_alcohol,
                        preparation_minutes=i.preparation_minutes,
                        is_out_of_stock=i.is_out_of_stock,
                    )
                    for i in rows
                ],
            )
        )

    return PublicMenu(
        property_name_ar=prop.name_ar,
        property_name_en=prop.name_en,
        outlet_code=outlet.code,
        outlet_name_ar=outlet.name_ar,
        outlet_name_en=outlet.name_en,
        outlet_type=outlet.outlet_type,
        currency=prop.currency,
        service_charge_percent=outlet.service_charge_percent,
        vat_percent=outlet.vat_percent,
        table_label=table_label,
        categories=groups,
        item_count=len(mine),
    )


@router.get(
    "/menu/{outlet_code}/qr.svg",
    summary="كود QR للمنفذ",
    response_class=Response,
    dependencies=[Depends(require("pos.view"))],
)
def menu_qr(
    outlet_code: str,
    db: DbSession,
    user: CurrentUser,
    prop: CurrentProperty,
    base_url: str = "",
    table: str | None = None,
    scale: int = 8,
) -> Response:
    """كود QR جاهز للطباعة ويتلصق على الطاولة.

    ``base_url`` بييجي من المتصفح عشان الكود يشاور على نفس العنوان اللي
    الشاشة مفتوحة منه — يعني على الشبكة المحلية بيشتغل من غير أي ضبط.
    """
    _prop, outlet = _outlet_or_404(db, outlet_code)

    root = (base_url or "").rstrip("/")
    target = f"{root}/menu/{outlet.code}"
    if table:
        target += f"?table={table}"

    # تصحيح خطأ متوسط: الكود بيفضل مقروء حتى لو اتوسّخ شوية على الطاولة
    code = segno.make(target, error="m")
    buffer = BytesIO()
    code.save(buffer, kind="svg", scale=scale, border=2, dark="#111", light=None)

    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
