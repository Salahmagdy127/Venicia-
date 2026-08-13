# برومبتات Google Stitch — شاشات فينيسيا

> **طريقة الاستخدام:** انسخ البرومبت كامل والصقه في Stitch. كل برومبت مستقل بذاته
> وفيه الألوان والنصوص العربية جاهزة، عشان اللي يطلع يركب على النظام من غير تعديل.
>
> **مهم:** الصق **كتلة الأساس** دي في أول كل برومبت — هي اللي بتضمن إن كل الشاشات
> تطلع بنفس الهوية.

---

## 🔹 كتلة الأساس (الصقها في أول كل برومبت)

```
DESIGN SYSTEM — apply strictly to every screen:

Direction: RIGHT-TO-LEFT (RTL). Arabic interface. Sidebar on the RIGHT side.
All UI labels in Arabic. All numbers, codes and dates in monospace, LTR, tabular.

Light palette:
  page background #F1F4F3 · card surface #FFFFFF · secondary surface #E6ECEA
  primary text #0D2A31 · secondary text #375257 · muted text #6B858A
  borders #D2DCDA · strong borders #97ABAD
  ACCENT (deep lake teal) #0E6F7A · accent tint #DBEDEE
  GOLD (money & alerts) #A8762F · gold tint #F4E9D8

Dark palette:
  page #0A1C21 · card #10262C · secondary #17343B
  text #E2EDEB / #AAC1C3 / #7D999D · borders #22434B
  accent #4FC2CC · accent tint #113A42 · gold #D6A55E

Reserved STATUS colors — use ONLY for real states, never decoration:
  confirmed #0E6F7A · checked-in #2E7350 · tentative #A8762F
  checked-out #6B858A · cancelled/no-show #A8433B

Style rules:
  Cards: flat surface + 1px border + 8px radius. NO shadows. NO gradients.
  Buttons: 6px radius, 40px height. Pills: fully rounded, 12% tint background.
  Spacing on a 4px scale. Table rows 44px tall.
  Typography: Segoe UI / Noto Sans Arabic for Arabic, monospace for all figures.
  NO emoji as icons. Use thin line icons only. Only ONE accent colour per screen.
  Clean, dense, professional hospitality software — not a consumer app.
```

---

## 1️⃣ شاشة الحجوزات — Tape Chart ⭐ (أهم شاشة)

```
[PASTE BASE BLOCK HERE]

Screen: "شاشة الحجوزات" — a hotel Tape Chart / reservation grid for a lakeside
resort, the main working screen of the front desk.

LAYOUT (RTL, sidebar on the right):

Right sidebar, 240px, dark teal surface, collapsible. Nav items with thin line
icons, Arabic labels, the active one highlighted with an accent tint background:
  الرئيسية · شاشة الحجوزات · الوصول والمغادرة · النزلاء · الكاشير ·
  الهاوس كيبينج · التقارير · الإعدادات
At the top of the sidebar: a compact resort logo block reading "فينيسيا".
At the bottom: user chip — avatar, "أحمد شريف", "استقبال".

Top bar, 64px: on the right a date range picker showing "12 – 26 أغسطس 2026",
arrows to move week by week, and a "النهاردة" button. In the middle a search
field "ابحث برقم الحجز أو اسم النزيل". On the left: occupancy summary chips —
"الإشغال 78%", "وصول اليوم 14", "مغادرة اليوم 9" — and a language toggle ع/EN
and a light/dark toggle.

MAIN GRID — this is the centrepiece:
  A horizontally scrolling calendar grid, 14 day columns.
  Column headers show weekday + day number, in Arabic (سبت 12، حد 13، …).
  Weekend columns (Friday & Saturday) have a subtly tinted background.
  Today's column has a 2px accent vertical line.

  Rows are grouped by unit category, each group with a sticky header row showing
  the category name and unit count, in a secondary surface:
    شاليهات على البحيرة (12) · شاليهات الحديقة (18) · فيلات (6)
    أجنحة (8) · خيام البحيرة (10) · غرف كلاسيك (24)

  Each unit row: fixed right-hand cell (140px) with the unit number "A-12",
  a small housekeeping status dot, and the zone name in muted text.

  RESERVATION BARS span across day columns — rounded 4px, 30px tall, showing
  the guest name and number of nights in small text inside the bar. Colour by
  status: confirmed teal #0E6F7A, checked-in green #2E7350, tentative gold
  #A8762F, checked-out muted grey #6B858A. Bars are draggable, with a subtle
  grab handle on each end for extending the stay.
  Show about 20 bars of varying lengths across the grid, realistic Arabic guest
  names (محمد عبد الرحمن، سارة الشناوي، عائلة منصور، Kevin Brooks).
  One row must show a hatched grey block labelled "صيانة" (out of order).
  One bar should be shown mid-drag with a dashed drop outline in the target row.

  An unassigned strip pinned above the grid: "حجوزات لم تُخصص (3)" containing
  3 small floating bars the user drags down onto a unit row.

Bottom status bar, 40px: a compact legend of the status colours in Arabic, and
on the left "آخر تحديث 14:32".
```

---

## 2️⃣ شاشة الكاشير + تصميم الصالة — POS

```
[PASTE BASE BLOCK HERE]

Screen: "الكاشير — مطعم البحيرة" — a restaurant point-of-sale, designed for a
TOUCH SCREEN. Every tappable target at least 48px.

LAYOUT (RTL): three columns.

RIGHT COLUMN (menu, widest ~50%):
  A horizontal row of category tabs as large pill buttons:
    الكل · مقبلات · شوربة · مشويات · أسماك · باستا · حلويات · مشروبات
  Below, a grid of menu item cards, 4 per row: each card has the dish name in
  Arabic, the English name beneath in muted text, and the price in monospace
  gold at the bottom (e.g. "٢٤٠ ج.م"). Cards are flat with a 1px border.
  Real dishes: سمك بلطي مشوي، جمبري بالثوم، كبدة إسكندراني، فراخ بانيه،
  مكرونة بالمأكولات البحرية، سلطة سيزر، أم علي، عصير مانجو طازة.
  Two cards shown greyed out with a "خلص النهاردة" ribbon.

MIDDLE COLUMN (the bill, ~28%):
  Header: "طاولة 12" plus a chip "4 أفراد" and the waiter name "كريم".
  A scrolling list of ordered lines: quantity, item name, line total in
  monospace. Each line has small + / − steppers and a delete icon.
  One line shows a note underneath in muted italic: "بدون بصل".
  One line has a small green "اتبعت للمطبخ" tag.
  Totals block at the bottom, right-aligned labels and monospace figures:
    الإجمالي · الخصم · خدمة 12% · ضريبة 14% · الإجمالي النهائي (large, gold)
  Action buttons in a 2×2 grid, full width, 56px tall:
    "إرسال للمطبخ" (accent, primary) · "خصم" (secondary, with a small lock icon)
    "تقسيم الفاتورة" · "تحصيل" (large, primary)
  Below them a row of settlement chips: نقدي · فيزا · على الغرفة · آجل.

LEFT COLUMN (floor plan, ~22%):
  Header "تصميم الصالة" with zone tabs: داخلي · تراس · على البحيرة.
  A visual floor plan: rounded square and circle table shapes laid out
  spatially, each labelled "١٢", "١٣" … with seat count beneath.
  Table colour encodes state: free = surface with border, occupied = accent
  tint with a filled accent border, reserved = gold tint, bill requested = a
  gold dot badge. The currently selected table 12 has a 2px accent ring.
  Below the plan, a compact summary: "مشغول 8 من 22".
```

---

## 3️⃣ داشبورد المالك

```
[PASTE BASE BLOCK HERE]

Screen: "داشبورد المالك" — an executive dashboard for the owner of a lakeside
resort, designed to be read at a glance on a laptop and on a phone.

LAYOUT (RTL):

Top: greeting "مساء الخير يا أستاذ محمود" with the date "الخميس ١٢ أغسطس ٢٠٢٦"
in muted monospace, and a period selector: اليوم · الأسبوع · الشهر · السنة.

KPI ROW — 5 flat cards in one row. Each card: small Arabic label at the top,
a LARGE monospace figure, and a small change indicator beneath (arrow + percent,
green for up, red for down, versus "الشهر اللي فات"):
  الإشغال            78%      ▲ 6%
  متوسط سعر الليلة   ١٬٤٢٠ ج.م  ▲ 3%      (label also shows "ADR" in tiny caps)
  إيراد الوحدة المتاحة ١٬١٠٧ ج.م ▲ 9%      (with "RevPAR" in tiny caps)
  إيراد النهاردة      ٣٨٤٬٢٠٠ ج.م ▲ 12%    (figure in GOLD)
  متوسط الفاتورة      ٣٢٥ ج.م   ▼ 2%

MAIN AREA — two columns:

  Right column (wider):
    Card "الإيراد والإشغال" — a combined chart: soft accent-tinted area chart
    for revenue across 30 days, with a thin gold line overlaid for occupancy on
    a secondary axis. Faint horizontal gridlines, emphasized last data point,
    a small hover tooltip visible on one day.

    Card "الإيراد حسب القسم" — a horizontal bar list with Arabic labels and
    monospace values and percentages:
      الإقامة ٦٢٪ · المطعم ١٩٪ · البار ٨٪ · السبا ٦٪ · الأنشطة ٥٪

  Left column (narrower):
    Card "عمولات القنوات" — THE MOST IMPORTANT CARD. A donut chart splitting
    direct vs OTA bookings, and beneath it a highlighted gold callout box:
      "عمولات دفعتها الشهر ده"  ٢١٤٬٦٠٠ ج.م
      and a muted line: "لو الحجز كان مباشر كنت وفّرت ١٨٢٬٤٠٠ ج.م"
    Channel rows below: بوكينج ٤٢٪ · مباشر ٣١٪ · أجودا ١٤٪ · إكسبيديا ٨٪ · إير بي إن بي ٥٪

    Card "يحتاج انتباهك" — a compact alert list, each row with a small coloured
    severity stripe on the right edge:
      • 3 حسابات مفتوحة من امبارح          (gold)
      • فرق درج الكاشير ‎-١٤٠ ج.م — وردية المسا (red)
      • 5 أصناف اتلغت بعد ما راحت المطبخ    (red)
      • غرفتين تحت الصيانة من 4 أيام        (gold)

Bottom: a wide card "حركة النهاردة" — a 4-column strip: الوصول ١٤ · المغادرة ٩ ·
نازلين حالياً ٨٦ · لم يحضروا ٢، each with a large monospace figure.
```

---

## 4️⃣ حساب النزيل — الفوليو

```
[PASTE BASE BLOCK HERE]

Screen: "حساب النزيل" — the open guest folio where every charge in the resort
lands, used by the front desk to review, transfer, split and settle.

LAYOUT (RTL):

Header card: guest name "محمد عبد الرحمن" with a gold "نزيل متكرر" pill and a
"VIP" pill; beneath it a metadata row in muted monospace:
  الوحدة A-12 · حجز VNC-2026-004821 · الوصول ١٠ أغسطس · المغادرة ١٧ أغسطس ·
  7 ليالي · بوكينج
On the left of the header, a balance block: label "الرصيد المستحق" and a LARGE
gold monospace figure "١٢٬٤٨٠ ج.م", with a primary "تحصيل" button beneath.

Toolbar row: filter chips — الكل · إقامة · مطعم · بار · سبا · أنشطة · مدفوعات
and on the left three secondary buttons: "إضافة حركة" · "تحويل لغرفة" ·
"تقسيم الفاتورة".

MAIN TABLE — the statement. Columns (right to left):
  التاريخ · البيان · المنفذ · الكمية · السعر · الخدمة · الضريبة · الإجمالي · بواسطة
  Rows 44px, figures in monospace right-aligned in their column.
  Charge rows in normal text; PAYMENT rows show the amount in green with a minus
  sign and a subtle green-tinted row background.
  Realistic lines: "إقامة ليلة ١٠ أغسطس"، "عشاء — مطعم البحيرة"، "مشروبات — البار"،
  "جلسة مساج ٦٠ دقيقة — السبا"، "رحلة قوارب"، "دفعة نقدي"، "عربون محوّل".
  One row is struck through with a red "ملغاة" pill and a tooltip icon.
  One row has a small transfer icon and muted text "محوّلة من A-14".
  Group rows by day with a subtle day separator showing the date and daily total.

Right-hand summary panel (or bottom card): a breakdown block —
  إجمالي الحركات · الخصومات · الخدمة ١٢٪ · الضريبة ١٤٪ · المدفوع · الرصيد (bold, gold)

Show a modal overlay for "تقسيم الفاتورة": two folio columns side by side with
line items that can be dragged between them, a running total under each, and
"إلغاء" / "تأكيد التقسيم" buttons.
```

---

## 5️⃣ الوصول والمغادرة + النزول السريع

```
[PASTE BASE BLOCK HERE]

Screen: "حركة اليوم" — the front desk daily worklist plus a quick check-in panel.

LAYOUT (RTL): two panes.

RIGHT PANE (list, ~62%):
  Three tabs with counts: "الوصول (14)" · "المغادرة (9)" · "نازلين حالياً (86)"
  A search field and filter chips: الكل · لم يصل · وصل · متأخر.
  A list of arrival cards, each 88px tall, flat with a 1px border:
    right side — a large circular initial avatar
    then guest name in bold, and beneath it in muted monospace:
      "VNC-2026-004821 · 7 ليالي · 2 كبار + 1 طفل · بوكينج"
    a category chip "شاليه على البحيرة" and the assigned unit "A-12"
      (or a gold "لم تُخصص" chip when empty)
    left side — expected arrival time "14:00" in monospace, a balance figure,
    and a primary "تسجيل النزول" button.
  One card has a red "لم يحضر" state, one has a green "وصل ١٣:٤٠" state,
  one shows a gold warning "العربون لم يُدفع".

LEFT PANE (check-in form, ~38%), appears when a card is selected:
  Header "تسجيل نزول — محمد عبد الرحمن" with a close icon.
  Stepper with 4 steps: البيانات · الهوية · الوحدة · التأكيد — step 2 active.
  Form fields with floating Arabic labels:
    الاسم بالكامل · الجنسية (dropdown with flags) · نوع الهوية (segmented
    control: الرقم القومي / جواز سفر) · رقم الهوية (monospace input) ·
    تاريخ الميلاد · رقم الموبايل · البريد الإلكتروني
  An ID capture block: a dashed-border drop zone with a camera icon and the
  label "صوّر البطاقة أو ارفع صورة", showing one captured thumbnail already.
  A preferences block with toggle chips: دور عالي · بعيد عن الضوضاء ·
  سرير إضافي · نباتي.
  A gold info strip: "النزيل ده نزل عندنا 4 مرات قبل كده — آخر مرة مارس 2026".
  Footer: secondary "حفظ كمسودة" and primary "تأكيد النزول" (full width, 48px).
```

---

## 6️⃣ لوحة الهاوس كيبينج (موبايل)

```
[PASTE BASE BLOCK HERE]

Screen: "الهاوس كيبينج" — a MOBILE screen (390×844) for the housekeeping
supervisor to change unit status live while walking the resort.

LAYOUT (RTL, mobile):
  Top bar: title "الهاوس كيبينج", date, and a sync indicator "متصل" with a
  small green dot.
  A summary strip of 4 tappable counters, horizontally scrollable:
    نظيفة ٤٢ (green) · متسخة ١٨ (gold) · جاري التنظيف ٦ (accent) ·
    صيانة ٣ (red) — each a flat card with a large monospace figure.
  Filter chips row: الكل · على البحيرة · الحديقة · الفيلات · الأجنحة.
  A vertical list of unit cards, each 76px tall and full width:
    right — a coloured status dot and the unit number "A-12" in bold monospace
    middle — zone name, and the occupancy state "فاضية" / "مشغولة — مغادرة اليوم"
    left — a status pill and a chevron
  Tapping a card opens a bottom sheet: unit number as the title, four large
  full-width status buttons stacked (نظيفة · متسخة · جاري التنظيف · تحت الصيانة),
  a note field "ملاحظة (اختياري)", a camera button "أرفق صورة", and a primary
  "حفظ" button. The sheet has a rounded top and a drag handle.
  A floating action button at the bottom-left: "تذكرة صيانة" with a plus icon.
```

---

## 📌 ملاحظات على الاستخدام

1. **ابدأ بشاشة الحجوزات** — هي أصعب واحدة وأهم واحدة في الميتنج. لو طلعت
   حلوة، الباقي أسهل.
2. **لو Stitch مطلعش العربي مظبوط:** جرّب تضيف في آخر البرومبت
   `All Arabic text must render right-to-left with correct letter joining.`
3. **لو طلع تصميم فيه ظلال أو تدرّجات:** ضيف
   `Absolutely no drop shadows, no gradients, no glassmorphism.`
4. **ابعتلي اللي هيطلع** — أنا هحوّله لكود React شغال على الـ API الحقيقي،
   مش صور.
