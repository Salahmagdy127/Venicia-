import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Locale = "ar" | "en";

/** قاموس الواجهة — كل مفتاح بالعربي والإنجليزي. */
const DICT: Record<string, [string, string]> = {
  // عام
  "app.name": ["فينيسيا", "Venicia"],
  "app.tagline": ["منتجع بحيرة فينيسيا", "Venicia Lake Resort"],
  "action.save": ["حفظ", "Save"],
  "action.cancel": ["إلغاء", "Cancel"],
  "action.confirm": ["تأكيد", "Confirm"],
  "action.close": ["إغلاق", "Close"],
  "action.search": ["بحث", "Search"],
  "action.today": ["النهاردة", "Today"],
  "action.retry": ["حاول تاني", "Retry"],
  "action.logout": ["تسجيل الخروج", "Sign out"],
  "state.loading": ["بيحمّل...", "Loading…"],
  "state.empty": ["مفيش بيانات", "No data"],
  "state.error": ["حصل خطأ", "Something went wrong"],

  // التنقل
  "nav.dashboard": ["الرئيسية", "Dashboard"],
  "nav.tapechart": ["شاشة الحجوزات", "Tape Chart"],
  "nav.frontdesk": ["الوصول والمغادرة", "Arrivals & Departures"],
  "nav.guests": ["النزلاء", "Guests"],
  "nav.pos": ["الكاشير", "Point of Sale"],
  "nav.housekeeping": ["الهاوس كيبينج", "Housekeeping"],
  "nav.reports": ["التقارير", "Reports"],
  "nav.settings": ["الإعدادات", "Settings"],

  // الدخول
  "login.title": ["تسجيل الدخول", "Sign in"],
  "login.username": ["اسم المستخدم", "Username"],
  "login.password": ["كلمة المرور", "Password"],
  "login.submit": ["دخول", "Sign in"],
  "login.error": ["اسم المستخدم أو كلمة المرور غير صحيحة", "Incorrect username or password"],
  "login.demo": ["حسابات التجربة", "Demo accounts"],

  // شاشة الحجوزات
  "tape.unit": ["الوحدة", "Unit"],
  "tape.unassigned": ["حجوزات لم تُخصص", "Unassigned"],
  "tape.occupancy": ["الإشغال", "Occupancy"],
  "tape.arrivals": ["وصول اليوم", "Arrivals"],
  "tape.departures": ["مغادرة اليوم", "Departures"],
  "tape.inhouse": ["نازلين حالياً", "In-house"],
  "tape.searchPlaceholder": ["ابحث برقم الحجز أو اسم النزيل", "Search by code or guest name"],
  "tape.maintenance": ["صيانة", "Maintenance"],
  "tape.lastUpdate": ["آخر تحديث", "Last update"],
  "tape.dropHint": ["اسحب الشريط لوحدة تانية", "Drag a bar to another unit"],
  "tape.nights": ["ليالي", "nights"],
  "tape.night": ["ليلة", "night"],
  "tape.units": ["وحدة", "units"],
  "tape.sold": ["مشغولة", "sold"],

  // الحالات
  "status.CONFIRMED": ["مؤكد", "Confirmed"],
  "status.CHECKED_IN": ["نازل", "Checked-in"],
  "status.TENTATIVE": ["مبدئي", "Tentative"],
  "status.CHECKED_OUT": ["غادر", "Checked-out"],
  "status.CANCELLED": ["ملغي", "Cancelled"],
  "status.NO_SHOW": ["لم يحضر", "No-show"],

  "hk.CLEAN": ["نظيفة", "Clean"],
  "hk.DIRTY": ["متسخة", "Dirty"],
  "hk.CLEANING": ["جاري التنظيف", "Cleaning"],
  "hk.INSPECTED": ["تم الفحص", "Inspected"],

  // المصادر
  "source.BOOKING_COM": ["بوكينج", "Booking.com"],
  "source.AGODA": ["أجودا", "Agoda"],
  "source.EXPEDIA": ["إكسبيديا", "Expedia"],
  "source.AIRBNB": ["إير بي إن بي", "Airbnb"],
  "source.WEBSITE": ["الموقع المباشر", "Website"],
  "source.DIRECT": ["حجز مباشر", "Direct"],
  "source.WALK_IN": ["حضور بدون حجز", "Walk-in"],
  "source.TRAVEL_AGENT": ["وكيل سفر", "Travel agent"],
  "source.CORPORATE": ["عقد شركات", "Corporate"],
  "source.POS": ["نقاط البيع", "Point of sale"],

  // الداشبورد
  "dash.greeting": ["أهلاً", "Welcome"],
  "dash.period.today": ["اليوم", "Today"],
  "dash.period.week": ["الأسبوع", "Week"],
  "dash.period.month": ["الشهر", "Month"],
  "dash.period.quarter": ["3 شهور", "Quarter"],
  "dash.period.year": ["السنة", "Year"],
  "dash.revenueTrend": ["الإيراد والإشغال", "Revenue & occupancy"],
  "dash.bySource": ["الإيراد حسب المصدر", "Revenue by source"],
  "dash.byOutlet": ["منافذ البيع", "Outlets"],
  "dash.commission": ["عمولات القنوات", "Channel commissions"],
  "dash.commissionPaid": ["عمولات مدفوعة في الفترة", "Commissions paid this period"],
  "dash.commissionSaving": [
    "لو نص دول كانوا حجز مباشر كنت وفّرت",
    "If half were direct you would have saved",
  ],
  "dash.directShare": ["نسبة الحجز المباشر", "Direct booking share"],
  "dash.alerts": ["يحتاج انتباهك", "Needs your attention"],
  "dash.noAlerts": ["مفيش حاجة تحتاج انتباه", "Nothing needs attention"],
  "dash.avgCheck": ["متوسط الفاتورة", "Average check"],
  "dash.orders": ["أوردر", "orders"],
  "dash.covers": ["فرد", "covers"],

  // الكاشير
  "pos.floorPlan": ["تصميم الصالة", "Floor plan"],
  "pos.menu": ["المنيو", "Menu"],
  "pos.all": ["الكل", "All"],
  "pos.table": ["طاولة", "Table"],
  "pos.covers": ["أفراد", "covers"],
  "pos.subtotal": ["الإجمالي", "Subtotal"],
  "pos.discount": ["الخصم", "Discount"],
  "pos.service": ["خدمة", "Service"],
  "pos.tax": ["ضريبة", "VAT"],
  "pos.total": ["الإجمالي النهائي", "Total"],
  "pos.sendKitchen": ["إرسال للمطبخ", "Send to kitchen"],
  "pos.settle": ["تحصيل", "Settle"],
  "pos.splitBill": ["تقسيم الفاتورة", "Split bill"],
  "pos.applyDiscount": ["خصم", "Discount"],
  "pos.cash": ["نقدي", "Cash"],
  "pos.card": ["فيزا", "Card"],
  "pos.roomCharge": ["على الغرفة", "Room charge"],
  "pos.cityLedger": ["آجل", "City ledger"],
  "pos.outOfStock": ["خلص النهاردة", "Out of stock"],
  "pos.sentToKitchen": ["اتبعت للمطبخ", "Sent to kitchen"],
  "pos.emptyOrder": ["اختار صنف من المنيو", "Pick an item from the menu"],
  "pos.pickTable": ["اختار طاولة من تصميم الصالة", "Pick a table from the floor plan"],
  "pos.occupied": ["مشغول", "occupied"],
  "pos.of": ["من", "of"],
  "pos.free": ["فاضية", "Free"],
  "pos.busy": ["مشغولة", "Occupied"],
  "pos.shift": ["الوردية", "Shift"],
  "pos.newOrder": ["أوردر جديد", "New order"],
  "pos.pickRoom": ["اختار الغرفة", "Pick a room"],
  "pos.voidReason": ["سبب الإلغاء", "Void reason"],
  "pos.discountReason": ["سبب الخصم", "Discount reason"],
  "pos.discountPercent": ["نسبة الخصم %", "Discount %"],

  // الفوليو
  "folio.title": ["حساب النزيل", "Guest folio"],
  "folio.balance": ["الرصيد المستحق", "Outstanding balance"],
  "folio.charges": ["الحركات", "Charges"],
  "folio.payments": ["المدفوع", "Payments"],
  "folio.settle": ["تحصيل", "Settle"],
  "folio.transfer": ["تحويل لغرفة", "Transfer"],
  "folio.addCharge": ["إضافة حركة", "Add charge"],
  "folio.void": ["إلغاء", "Void"],
  "folio.voided": ["ملغاة", "Voided"],
  "folio.transferred": ["محوّلة", "Transferred"],
  "folio.date": ["التاريخ", "Date"],
  "folio.description": ["البيان", "Description"],
  "folio.qty": ["الكمية", "Qty"],
  "folio.price": ["السعر", "Price"],
  "folio.amount": ["الإجمالي", "Amount"],
  "folio.dayTotal": ["إجمالي اليوم", "Day total"],
  "folio.returning": ["نزيل متكرر", "Returning guest"],
  "folio.stays": ["إقامة", "stays"],
  "folio.open": ["مفتوح", "Open"],
  "folio.closed": ["مقفول", "Closed"],

  // الاستقبال
  "desk.arrivals": ["الوصول", "Arrivals"],
  "desk.departures": ["المغادرة", "Departures"],
  "desk.inhouse": ["نازلين حالياً", "In-house"],
  "desk.checkIn": ["تسجيل النزول", "Check in"],
  "desk.checkOut": ["تسجيل المغادرة", "Check out"],
  "desk.notAssigned": ["لم تُخصص", "Unassigned"],
  "desk.adults": ["كبار", "adults"],
  "desk.children": ["أطفال", "children"],

  // الهاوس كيبينج
  "hk.title": ["الهاوس كيبينج", "Housekeeping"],
  "hk.occupied": ["مشغولة", "Occupied"],
  "hk.vacant": ["فاضية", "Vacant"],
  "hk.departsToday": ["مغادرة اليوم", "Departs today"],
  "hk.arrivesToday": ["وصول اليوم", "Arrives today"],
  "hk.outOfOrder": ["خارج الخدمة", "Out of order"],

  // شاشة الحجوزات — إضافات
  "tape.days": ["يوم", "days"],
  "tape.free": ["متاح", "Free"],
  "tape.full": ["مقفول", "Full"],
  "tape.legend": ["الدليل", "Legend"],
  "tape.ooo": ["خارج الخدمة", "Out of order"],
  "tape.dragging": ["سيبه على الوحدة الجديدة", "Drop it on the new unit"],
  "tape.moved": ["تم نقل الحجز", "Reservation moved"],
  "tape.noUnassigned": ["كل الحجوزات متخصصة", "Every reservation is assigned"],
  "tape.unassignedHint": [
    "اسحبهم على الوحدة المناسبة",
    "Drag each onto a unit",
  ],
  "tape.prev": ["أسبوع قبل", "Previous week"],
  "tape.next": ["أسبوع بعد", "Next week"],
  "tape.balanceDue": ["عليه رصيد", "Balance due"],
  "tape.vip": ["VIP", "VIP"],

  // تفاصيل الحجز
  "res.details": ["تفاصيل الحجز", "Reservation"],
  "res.code": ["رقم الحجز", "Code"],
  "res.guest": ["النزيل", "Guest"],
  "res.phone": ["الموبايل", "Phone"],
  "res.stay": ["الإقامة", "Stay"],
  "res.unit": ["الوحدة", "Unit"],
  "res.source": ["المصدر", "Source"],
  "res.status": ["الحالة", "Status"],
  "res.guests": ["عدد الأفراد", "Guests"],
  "res.roomTotal": ["إيراد الإقامة", "Accommodation"],
  "res.discount": ["الخصم", "Discount"],
  "res.service": ["خدمة 12%", "Service 12%"],
  "res.tax": ["ضريبة 14%", "VAT 14%"],
  "res.grandTotal": ["الإجمالي", "Grand total"],
  "res.paid": ["المدفوع", "Paid"],
  "res.balance": ["المستحق", "Balance"],
  "res.commission": ["عمولة القناة", "Channel commission"],
  "res.requests": ["طلبات خاصة", "Special requests"],
  "res.cancel": ["إلغاء الحجز", "Cancel reservation"],
  "res.cancelReason": ["سبب الإلغاء", "Cancellation reason"],
  "res.chargePenalty": ["احتساب غرامة الإلغاء", "Charge cancellation penalty"],
  "res.forceCheckout": ["مغادرة رغم وجود رصيد", "Check out despite balance"],
  "res.openFolio": ["فتح الحساب", "Open folio"],

  // حجز جديد
  "book.new": ["حجز جديد", "New reservation"],
  "book.stay": ["الإقامة", "Stay"],
  "book.arrival": ["الوصول", "Arrival"],
  "book.departure": ["المغادرة", "Departure"],
  "book.category": ["فئة الوحدة", "Unit category"],
  "book.ratePlan": ["خطة السعر", "Rate plan"],
  "book.adults": ["كبار", "Adults"],
  "book.children": ["أطفال", "Children"],
  "book.source": ["مصدر الحجز", "Booking source"],
  "book.quote": ["التسعيرة", "Quote"],
  "book.perNight": ["السعر ليلة بليلة", "Nightly breakdown"],
  "book.published": ["السعر المعلن", "Published"],
  "book.applied": ["القواعد المطبّقة", "Rules applied"],
  "book.available": ["متاح", "available"],
  "book.notAvailable": ["مفيش إتاحة في التواريخ دي", "No availability for these dates"],
  "book.guest": ["النزيل", "Guest"],
  "book.searchGuest": ["ابحث بالاسم أو التليفون أو الرقم القومي", "Search name, phone, or ID"],
  "book.newGuest": ["نزيل جديد", "New guest"],
  "book.existingGuest": ["نزيل مسجّل", "Existing guest"],
  "book.firstName": ["الاسم الأول", "First name"],
  "book.lastName": ["اسم العيلة", "Last name"],
  "book.idType": ["نوع الهوية", "ID type"],
  "book.idNumber": ["رقم الهوية", "ID number"],
  "book.nationality": ["الجنسية", "Nationality"],
  "book.deposit": ["العربون", "Deposit"],
  "book.depositHint": ["المبلغ اللي اتحصّل دلوقتي", "Amount collected now"],
  "book.confirm": ["تأكيد الحجز", "Confirm reservation"],
  "book.created": ["تم الحجز", "Reservation created"],
  "book.notes": ["طلبات خاصة", "Special requests"],
  "book.pickGuest": ["اختار النزيل الأول", "Pick a guest first"],
  "book.avgNight": ["متوسط الليلة", "Average night"],
  "book.unassignedNote": [
    "الحجز هيتعمل من غير تخصيص وحدة — تسحبه من الشريط على الوحدة اللي تناسبه.",
    "The reservation is created unassigned — drag it from the strip onto a unit.",
  ],
  "book.rule.WKND": ["ويك إند", "Weekend"],
  "book.rule.MIDWEEK": ["وسط الأسبوع", "Midweek"],
  "book.rule.LOWOCC": ["إشغال منخفض", "Low occupancy"],
  "book.rule.HIGHOCC": ["إشغال عالي", "High occupancy"],
  "book.rule.EID": ["عيد", "Eid"],
  "book.rule.HOLIDAY": ["إجازة رسمية", "Holiday"],

  "id.NATIONAL_ID": ["رقم قومي", "National ID"],
  "id.PASSPORT": ["باسبور", "Passport"],
  "id.DRIVING_LICENSE": ["رخصة قيادة", "Driving licence"],

  // الفوليو — إضافات
  "folio.statement": ["كشف الحساب", "Statement"],
  "folio.settleTitle": ["تحصيل من الحساب", "Take a payment"],
  "folio.method": ["طريقة الدفع", "Payment method"],
  "folio.amount2": ["المبلغ", "Amount"],
  "folio.reference": ["رقم مرجعي", "Reference"],
  "folio.close": ["إقفال الحساب", "Close folio"],
  "folio.chargeKind": ["نوع الحركة", "Charge type"],
  "folio.chargeDesc": ["البيان", "Description"],
  "folio.applyService": ["احتساب الخدمة", "Apply service charge"],
  "folio.applyTax": ["احتساب الضريبة", "Apply VAT"],
  "folio.voidReason": ["سبب الإلغاء", "Void reason"],
  "folio.noFolio": ["اختار حساب من القايمة", "Pick a folio from the list"],
  "folio.pos": ["من الكاشير", "From POS"],

  "folio.voidNote": [
    "الحركة مش بتتمسح — بيتسجّل قيد عكسي، وده اللي بيخلي الحساب قابل للمراجعة.",
    "Nothing is deleted — a reversing entry is recorded, which keeps the folio auditable.",
  ],

  // طرق الدفع
  "pay.CASH": ["نقدي", "Cash"],
  "pay.CARD": ["فيزا", "Card"],
  "pay.FAWRY": ["فوري", "Fawry"],
  "pay.PAYMOB": ["باي موب", "Paymob"],
  "pay.INSTAPAY": ["إنستا باي", "InstaPay"],
  "pay.BANK_TRANSFER": ["تحويل بنكي", "Bank transfer"],
  "pay.CHEQUE": ["شيك", "Cheque"],
  "pay.CITY_LEDGER": ["آجل", "City ledger"],
  "pay.OTA_PREPAID": ["محصّل من القناة", "OTA prepaid"],
  "pay.COMPLIMENTARY": ["ضيافة", "Complimentary"],

  // أنواع الحركات
  "kind.ROOM": ["إيجار الوحدة", "Accommodation"],
  "kind.FNB": ["مأكولات ومشروبات", "Food & beverage"],
  "kind.SPA": ["سبا", "Spa"],
  "kind.ACTIVITY": ["أنشطة ورحلات", "Activities"],
  "kind.MINIBAR": ["ميني بار", "Minibar"],
  "kind.LAUNDRY": ["مغسلة", "Laundry"],
  "kind.ADJUSTMENT": ["تسوية", "Adjustment"],
  "kind.PAYMENT": ["دفعة", "Payment"],
  "kind.DEPOSIT": ["عربون", "Deposit"],
  "kind.DISCOUNT": ["خصم", "Discount"],

  // التقسيم والتحويل
  "folio.select": ["اختار حركات", "Select charges"],
  "folio.selected": ["محدّدة", "selected"],
  "folio.cancelSelect": ["إلغاء التحديد", "Clear"],
  "folio.splitTitle": ["تقسيم الفاتورة", "Split bill"],
  "folio.splitHint": [
    "الحركات المحددة هتتنقل لحساب جديد بنفس النزيل — الأصل بيفضل مكتوب ومتعلّم إنه اتحوّل.",
    "The selected charges move to a new folio for the same guest — the originals stay recorded as transferred.",
  ],
  "folio.splitLabel": ["اسم الحساب الجديد", "New folio label"],
  "folio.splitDo": ["اعمل حساب جديد", "Create folio"],
  "folio.transferTitle": ["تحويل لغرفة تانية", "Transfer to another room"],
  "folio.transferHint": [
    "اختار الغرفة اللي الحركات هتروحلها.",
    "Pick the room the charges should move to.",
  ],
  "folio.transferDo": ["حوّل", "Transfer"],
  "folio.pickTarget": ["اختار الحساب", "Pick a folio"],
  "folio.searchFolio": ["ابحث برقم الوحدة أو اسم النزيل", "Search unit or guest"],
  "folio.selectedTotal": ["إجمالي المحدّد", "Selected total"],
  "folio.noneSelectable": ["مفيش حركات تنفع تتحوّل", "No transferable charges"],

  // ملف النزيل
  "gp.title": ["ملف النزيل", "Guest profile"],
  "gp.edit": ["تعديل الملف", "Edit profile"],
  "gp.identity": ["الهوية", "Identity"],
  "gp.contact": ["التواصل", "Contact"],
  "gp.prefs": ["التفضيلات", "Preferences"],
  "gp.prefsHint": [
    "اللي بيتحفظ هنا بيظهر لموظف الاستقبال أول ما النزيل يرجع.",
    "Anything saved here shows to the front desk the moment this guest returns.",
  ],
  "gp.occasions": ["المناسبات", "Occasions"],
  "gp.dietary": ["حساسيات وملاحظات المطعم", "Dietary notes"],
  "gp.notes": ["ملاحظات داخلية", "Internal notes"],
  "gp.markVip": ["نزيل VIP", "VIP guest"],
  "gp.whatsapp": ["يستقبل واتساب", "Receives WhatsApp"],
  "gp.marketing": ["يستقبل عروض", "Receives offers"],
  "gp.addPref": ["إضافة تفضيل", "Add preference"],
  "gp.prefKey": ["البند", "Item"],
  "gp.prefValue": ["التفاصيل", "Detail"],
  "gp.saved": ["اتحفظ", "Saved"],
  "gp.noPrefs": ["مفيش تفضيلات متسجّلة", "No preferences recorded"],
  "gp.returningBanner": [
    "النزيل ده كان عندنا قبل كده",
    "This guest has stayed with us before",
  ],

  // الاستقبال — إضافات
  "desk.searchPlaceholder": ["ابحث بالاسم أو رقم الحجز", "Search name or code"],
  "desk.noArrivals": ["مفيش وصول النهاردة", "No arrivals today"],
  "desk.noDepartures": ["مفيش مغادرة النهاردة", "No departures today"],
  "desk.openFolios": ["الحسابات المفتوحة", "Open folios"],
  "desk.nights": ["ليالي", "nights"],

  // النزلاء
  "guest.title": ["النزلاء", "Guests"],
  "guest.search": ["ابحث بالاسم أو التليفون أو رقم الهوية", "Search name, phone, or ID"],
  "guest.returningOnly": ["المتكررين بس", "Returning only"],
  "guest.stays": ["إقامات", "Stays"],
  "guest.nights": ["ليالي", "Nights"],
  "guest.revenue": ["إجمالي الإنفاق", "Total spend"],
  "guest.lastStay": ["آخر إقامة", "Last stay"],
  "guest.loyalty": ["نقاط الولاء", "Loyalty points"],
  "guest.phone": ["الموبايل", "Phone"],
  "guest.city": ["المدينة", "City"],
  "guest.idNumber": ["رقم الهوية", "ID number"],
  "guest.loadMore": ["حمّل المزيد", "Load more"],
  "guest.blacklisted": ["محظور", "Blacklisted"],
  "guest.whatsapp": ["واتساب", "WhatsApp"],

  // الهاوس كيبينج — إضافات
  "hk.board": ["لوحة النظافة", "Housekeeping board"],
  "hk.markClean": ["نظيفة", "Clean"],
  "hk.markDirty": ["متسخة", "Dirty"],
  "hk.markCleaning": ["جاري التنظيف", "Cleaning"],
  "hk.markInspected": ["تم الفحص", "Inspected"],
  "hk.priority": ["الأولوية النهاردة", "Today's priority"],
  "hk.priorityHint": [
    "الوحدات اللي هتغادر ومعاها وصول في نفس اليوم",
    "Units departing with an arrival the same day",
  ],
  "hk.allUnits": ["كل الوحدات", "All units"],
  "hk.condition": ["الحالة الفنية", "Condition"],

  "cond.OPERATIONAL": ["صالحة", "Operational"],
  "cond.MAINTENANCE": ["تحت الصيانة", "Maintenance"],
  "cond.OUT_OF_ORDER": ["خارج الخدمة", "Out of order"],
  "cond.OUT_OF_SERVICE": ["موقوفة", "Out of service"],

  // التقارير
  "rep.title": ["التقارير", "Reports"],
  "rep.daily": ["اليومية التفصيلية", "Daily breakdown"],
  "rep.date": ["التاريخ", "Date"],
  "rep.roomRevenue": ["إيراد الإقامة", "Room revenue"],
  "rep.otherRevenue": ["إيرادات أخرى", "Other revenue"],
  "rep.total": ["الإجمالي", "Total"],
  "rep.print": ["طباعة", "Print"],

  // تقفيل اليوم
  "na.title": ["تقفيل اليوم", "Night audit"],
  "na.subtitle": [
    "بيرحّل ليالي الإقامة، يعلّم اللي مجاش، ويقفل أرقام اليوم.",
    "Posts room nights, marks no-shows, and closes the day's numbers.",
  ],
  "na.businessDate": ["اليوم المحاسبي", "Business date"],
  "na.run": ["قفّل اليوم", "Run audit"],
  "na.rerun": ["أعِد التقفيل", "Re-run"],
  "na.done": ["اتقفل", "Audited"],
  "na.pending": ["مستني التقفيل", "Not audited yet"],
  "na.willPost": ["ليالي هتترحّل", "Nights to post"],
  "na.willNoShow": ["هيتعلّم عدم حضور", "Will be marked no-show"],
  "na.needsAttention": ["محتاج تدخّل قبل ما تقفّل", "Needs attention before you close"],
  "na.openFolios": ["حسابات مفتوحة", "Open folios"],
  "na.openOrders": ["أوردرات مفتوحة", "Open orders"],
  "na.openShifts": ["ورديات مفتوحة", "Open shifts"],
  "na.noUnit": ["نازل من غير وحدة", "In-house without a unit"],
  "na.overdue": ["متأخر عن المغادرة", "Overdue checkout"],
  "na.allClear": ["كل حاجة تمام", "All clear"],
  "na.history": ["سجل التقفيلات", "Audit history"],
  "na.nightsPosted": ["ليالي مرحّلة", "Nights posted"],
  "na.revenuePosted": ["إيراد مرحّل", "Revenue posted"],
  "na.noShows": ["عدم حضور", "No-shows"],
  "na.ranAt": ["وقت التنفيذ", "Ran at"],
  "na.auto": ["تلقائي", "Automatic"],
  "na.manual": ["يدوي", "Manual"],
  "na.rerunHint": [
    "اليوم ده اتقفل قبل كده. إعادة التقفيل بتعيد حساب الملخّص بس — مبتكرّرش ترحيل ولا غرامة.",
    "This day was already audited. Re-running only recomputes the summary — it never double-posts.",
  ],
  "na.COMPLETED": ["تم", "Completed"],
  "na.FAILED": ["فشل", "Failed"],
  "na.RUNNING": ["بيشتغل", "Running"],

  // الإعدادات
  "set.property": ["بيانات المنشأة", "Property"],
  "set.categories": ["فئات الوحدات", "Unit categories"],
  "set.ratePlans": ["خطط الأسعار", "Rate plans"],
  "set.account": ["حسابك", "Your account"],
  "set.permissions": ["صلاحياتك", "Your permissions"],
  "set.appearance": ["المظهر واللغة", "Appearance & language"],
  "set.baseRate": ["السعر الأساسي", "Base rate"],
  "set.occupancy": ["الإشغال", "Occupancy"],
  "set.units": ["وحدة", "units"],
  "set.maxDiscount": ["أقصى خصم", "Max discount"],

  // الكاشير — إضافات
  "pos.outlet": ["المنفذ", "Outlet"],
  "pos.seats": ["كرسي", "seats"],
  "pos.openShift": ["فتح وردية", "Open shift"],
  "pos.closeShift": ["تقفيل الوردية", "Close shift"],
  "pos.openingFloat": ["عهدة البداية", "Opening float"],
  "pos.countedCash": ["النقدي المعدود", "Counted cash"],
  "pos.countedCard": ["الفيزا المعدودة", "Counted card"],
  "pos.expectedCash": ["المفروض نقدي", "Expected cash"],
  "pos.expectedCard": ["المفروض فيزا", "Expected card"],
  "pos.variance": ["الفرق", "Variance"],
  "pos.shiftOrders": ["أوردرات الوردية", "Shift orders"],
  "pos.void": ["إلغاء صنف", "Void item"],
  "pos.qty": ["الكمية", "Qty"],
  "pos.item": ["الصنف", "Item"],
  "pos.reason": ["السبب", "Reason"],
  "pos.kotSent": ["راح المطبخ", "In kitchen"],
  "pos.kotNew": ["لسه متبعتش", "Not sent"],
  "pos.noOpenTable": ["مفيش أوردر مفتوح", "No open order"],
  "pos.newOrderCovers": ["عدد الأفراد على الطاولة", "Covers at this table"],
  "pos.openTable": ["فتح الطاولة", "Open table"],
  "pos.maxDiscount": ["أقصى خصم مسموح لك", "Your maximum discount"],
  "pos.settleTitle": ["تحصيل الأوردر", "Settle order"],
  "pos.searchRoom": ["ابحث برقم الوحدة أو اسم النزيل", "Search by unit or guest"],
  "pos.searchItem": ["ابحث في المنيو", "Search the menu"],
  "pos.vegetarian": ["نباتي", "Vegetarian"],
  "pos.alcohol": ["كحولي", "Alcohol"],
  "pos.zones": ["المناطق", "Zones"],
  "pos.orderOn": ["أوردر على", "Order on"],
  "pos.settled": ["تم التحصيل", "Settled"],

  // الداشبورد — إضافات
  "dash.otaBookings": ["حجوزات عن طريق القنوات", "OTA bookings"],
  "dash.directBookings": ["حجوزات مباشرة", "Direct bookings"],
  "dash.netSales": ["صافي المبيعات", "Net sales"],
  "dash.cost": ["تكلفة الخامات", "Cost of sales"],
  "dash.voids": ["إلغاءات بعد المطبخ", "Voids after send"],
  "dash.share": ["النسبة", "Share"],
  "dash.outlet": ["المنفذ", "Outlet"],
  "dash.revenue": ["الإيراد", "Revenue"],
  "dash.occupancy": ["الإشغال", "Occupancy"],
  "dash.margin": ["هامش الربح", "Margin"],
  "dash.commissionNote": [
    "ده اللي القنوات أخدته من إيرادك في الفترة دي.",
    "This is what the channels took from your revenue in this period.",
  ],
};

type Ctx = {
  locale: Locale;
  dir: "rtl" | "ltr";
  t: (key: string, fallback?: string) => string;
  /** يختار الحقل العربي أو الإنجليزي من كائن جاي من الـ API */
  pick: (obj: { name_ar?: string | null; name_en?: string | null } | null | undefined) => string;
  setLocale: (l: Locale) => void;
  toggle: () => void;
};

const I18nContext = createContext<Ctx | null>(null);
const STORAGE_KEY = "venicia.locale";

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(
    () => (localStorage.getItem(STORAGE_KEY) as Locale) || "ar",
  );

  useEffect(() => {
    const dir = locale === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
    localStorage.setItem(STORAGE_KEY, locale);
  }, [locale]);

  const t = useCallback(
    (key: string, fallback?: string) => {
      const entry = DICT[key];
      if (!entry) return fallback ?? key;
      return locale === "ar" ? entry[0] : entry[1];
    },
    [locale],
  );

  const pick = useCallback(
    (obj: { name_ar?: string | null; name_en?: string | null } | null | undefined) => {
      if (!obj) return "—";
      return (locale === "ar" ? obj.name_ar : obj.name_en) || obj.name_ar || obj.name_en || "—";
    },
    [locale],
  );

  const value = useMemo<Ctx>(
    () => ({
      locale,
      dir: locale === "ar" ? "rtl" : "ltr",
      t,
      pick,
      setLocale: setLocaleState,
      toggle: () => setLocaleState((l) => (l === "ar" ? "en" : "ar")),
    }),
    [locale, t, pick],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}
