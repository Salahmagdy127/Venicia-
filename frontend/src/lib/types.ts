/** أنواع الاستجابات الجاية من الـ API — مطابقة لنماذج Pydantic في الباك إند. */

export type ReservationStatus =
  | "TENTATIVE"
  | "CONFIRMED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED"
  | "NO_SHOW";

export type ReservationLine = {
  id: number;
  unit_category_id: number;
  unit_id: number | null;
  unit_label: string | null;
  rate_plan_id: number;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  status: ReservationStatus;
  room_total: string;
};

export type Reservation = {
  id: number;
  code: string;
  status: ReservationStatus;
  source: string;
  external_reference: string | null;
  guest_id: number;
  guest_name: string | null;
  guest_phone: string | null;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  room_total: string;
  discount_total: string;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  paid_total: string;
  balance: string;
  channel_commission_amount: string;
  special_requests: string | null;
  units: ReservationLine[];
};

export type ActionResult = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  reservation?: Reservation | null;
  penalty?: string | null;
  folio_ids?: number[];
};

/* ───────────────────────────────────────────── حساب النزيل */
export type StatementLine = {
  id: number;
  created_at: string;
  business_date: string;
  charge_kind: string;
  charge_label_ar: string;
  description_ar: string;
  description_en: string | null;
  quantity: string;
  unit_price: string;
  amount: string;
  service_charge_amount: string;
  tax_amount: string;
  total_amount: string;
  is_credit: boolean;
  is_void: boolean;
  is_transferred: boolean;
  transferred_from_folio_id: number | null;
  outlet_id: number | null;
  pos_order_id: number | null;
};

export type DayGroup = {
  business_date: string;
  lines: StatementLine[];
  day_total: string;
};

export type Folio = {
  id: number;
  code: string;
  status: string;
  unit_label: string | null;
  guest_id: number | null;
  guest_name: string | null;
  guest_phone: string | null;
  is_vip: boolean;
  is_returning: boolean;
  total_stays: number;
  reservation_id: number | null;
  reservation_code: string | null;
  arrival_date: string | null;
  departure_date: string | null;
  nights: number | null;
  source: string | null;
  charges_total: string;
  payments_total: string;
  discount_total: string;
  service_charge_total: string;
  tax_total: string;
  balance: string;
  opened_at: string;
  closed_at: string | null;
  days: DayGroup[];
};

export type FolioListItem = {
  id: number;
  code: string;
  status: string;
  unit_label: string | null;
  guest_name: string;
  balance: string;
  opened_at: string;
};

export type FolioAction = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  folio: Folio | null;
  new_folio_id: number | null;
};

/* ─────────────────────────────────────────────────── النزلاء */
export type Guest = {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  nationality: string;
  id_type: string;
  id_number: string | null;
  phone: string | null;
  email: string | null;
  city: string | null;
  is_vip: boolean;
  is_blacklisted: boolean;
  total_stays: number;
  total_nights: number;
  total_revenue: string;
  last_stay_date: string | null;
  loyalty_points: number;
  whatsapp_opt_in: boolean;
  marketing_opt_in?: boolean;
  preferences?: Record<string, unknown> | null;
  occasions?: Record<string, unknown> | null;
  dietary_notes?: string | null;
  notes?: string | null;
};

export type GuestPage = { items: Guest[]; next_cursor: string | null; has_more: boolean };

/* ────────────────────────────────────────────── الهاوس كيبينج */
export type UnitStatus = {
  id: number;
  label: string;
  category_id: number;
  category_name_ar: string;
  zone_ar: string | null;
  zone_en: string | null;
  housekeeping_status: string;
  condition: string;
  block_reason: string | null;
  is_occupied: boolean;
  departs_today: boolean;
  arrives_today: boolean;
};

export type HousekeepingBoard = {
  business_date: string;
  clean: number;
  dirty: number;
  cleaning: number;
  inspected: number;
  out_of_order: number;
  units: UnitStatus[];
};

/* ───────────────────────────────────────── الفئات وخطط الأسعار */
export type UnitCategoryOut = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  kind: string;
  base_occupancy: number;
  max_occupancy: number;
  base_rate: string;
  extra_adult_rate: string;
  extra_child_rate: string;
  unit_count: number;
};

export type RatePlan = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  meal_plan: string;
  is_public: boolean;
};

export type NightQuote = {
  stay_date: string;
  published_rate: string;
  rate: string;
  extra_person_amount: string;
  applied_rules: string[];
};

export type Quote = {
  unit_category_id: number;
  rate_plan_id: number;
  arrival_date: string;
  departure_date: string;
  nights: number;
  available: number;
  is_available: boolean;
  room_total: string;
  extras_total: string;
  discount_total: string;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  average_nightly_rate: string;
  nights_detail: NightQuote[];
};

export type ReservationListItem = {
  id: number;
  code: string;
  status: ReservationStatus;
  source: string;
  guest_name: string;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  grand_total: string;
  balance: string;
};

/* ───────────────────────────────────────────────── الكاشير */
export type Outlet = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  outlet_type: string;
  has_floor_plan: boolean;
  allows_room_charge: boolean;
  service_charge_percent: string;
  vat_percent: string;
  order_prefix: string;
};

export type PosTable = {
  id: number;
  label: string;
  zone_ar: string | null;
  zone_en: string | null;
  seats: number;
  status: string;
  pos_x: number;
  pos_y: number;
  width: number;
  height: number;
  shape: string;
  open_order_id: number | null;
  open_order_total: string | null;
};

export type FloorPlan = {
  outlet_id: number;
  name_ar: string;
  name_en: string;
  tables: PosTable[];
  occupied: number;
  total: number;
};

export type MenuItem = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  category_id: number;
  price: string;
  is_available: boolean;
  is_out_of_stock: boolean;
  is_vegetarian: boolean;
  contains_alcohol: boolean;
  preparation_minutes: number | null;
  kitchen_station_id: number | null;
};

export type MenuCategory = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  sort_order: number;
  items: MenuItem[];
};

export type Menu = { outlet_id: number; categories: MenuCategory[]; item_count: number };

export type OrderLine = {
  id: number;
  menu_item_id: number | null;
  item_name_ar: string;
  item_name_en: string | null;
  quantity: string;
  unit_price: string;
  line_total: string;
  notes: string | null;
  kot_status: string;
  is_void: boolean;
  voided_after_send: boolean;
};

export type PosOrder = {
  id: number;
  code: string;
  outlet_id: number;
  business_date: string;
  order_type: string;
  status: string;
  table_id: number | null;
  table_label: string | null;
  covers: number;
  folio_id: number | null;
  unit_label: string | null;
  subtotal: string;
  discount_percent: string;
  discount_total: string;
  discount_reason: string | null;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  settlement_type: string | null;
  opened_at: string;
  is_void: boolean;
  lines: OrderLine[];
};

export type InHouse = {
  folio_id: number;
  unit_label: string | null;
  guest_name: string;
  reservation_code: string | null;
  balance: string;
};

export type Shift = {
  id: number;
  code: string;
  status: string;
  business_date: string;
  opening_float: string;
  expected_cash: string;
  expected_card: string;
  counted_cash: string;
  counted_card: string;
  variance: string;
  orders_count: number;
  voids_count: number;
  discounts_total: string;
};

/* ───────────────────────────────────────────── تدقيق الليلة */
export type AuditWarnings = {
  open_folios: number;
  open_pos_orders: number;
  open_shifts: number;
  in_house_without_unit: number;
  overdue_checkouts: number;
};

export type NightAuditRun = {
  id: number;
  business_date: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  nights_posted: number;
  room_revenue_posted: string;
  no_shows_marked: number;
  open_folios_remaining: number;
  warnings: AuditWarnings | null;
  error_message: string | null;
  is_automatic: boolean;
};

export type AuditPreview = {
  business_date: string;
  already_done: boolean;
  pending_no_shows: number;
  pending_nights: number;
  warnings: AuditWarnings;
};

/* ─────────────────────────────────────────────── الداشبورد */
export type Kpi = {
  key: string;
  label_ar: string;
  label_en: string;
  value: string;
  unit: "percent" | "money" | "count";
  change_percent: number | null;
  is_money: boolean;
};

export type TrendPoint = {
  date: string;
  revenue: string;
  room_revenue: string;
  occupancy_percent: string;
  adr: string;
  revpar: string;
};

export type SourceSlice = {
  source: string;
  label_ar: string;
  bookings: number;
  revenue: string;
  commission: string;
  share_percent: number;
};

export type OutletSlice = {
  outlet_id: number;
  name_ar: string;
  name_en: string;
  net_sales: string;
  orders: number;
  covers: number;
  average_check: string;
  cost_of_sales: string;
  void_count: number;
  void_after_send_count: number;
  share_percent: number;
};

export type Alert = {
  severity: "warning" | "critical";
  message_ar: string;
  message_en: string;
  value: string | null;
};

export type DashboardData = {
  period: string;
  start_date: string;
  end_date: string;
  kpis: Kpi[];
  trend: TrendPoint[];
  by_source: SourceSlice[];
  by_outlet: OutletSlice[];
  commission: {
    total_commission: string;
    ota_bookings: number;
    direct_bookings: number;
    direct_share_percent: number;
    potential_saving: string;
  };
  alerts: Alert[];
};

/* ─────────────────────────────────────────── شاشة الحجوزات */
export type DayCell = {
  date: string;
  weekday: number;
  weekday_ar: string;
  weekday_en: string;
  day: number;
  month_ar: string;
  is_weekend: boolean;
  is_today: boolean;
};

export type UnitRow = {
  id: number;
  label: string;
  zone_ar: string | null;
  zone_en: string | null;
  housekeeping_status: string;
  condition: string;
  is_sellable: boolean;
};

export type CategoryGroup = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  unit_count: number;
  sold_today: number;
  units: UnitRow[];
};

export type Bar = {
  id: number;
  reservation_id: number;
  code: string;
  unit_id: number | null;
  unit_category_id: number;
  guest_name: string;
  guest_id: number;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  status: ReservationStatus;
  source: string;
  balance: string;
  is_vip: boolean;
  start_index: number;
  span: number;
};

export type DayAvailability = {
  date: string;
  unit_category_id: number;
  available: number;
  sold: number;
  total: number;
  occupancy_percent: number;
  is_closed: boolean;
};

export type TapeChartData = {
  start_date: string;
  end_date: string;
  today: string;
  days: DayCell[];
  categories: CategoryGroup[];
  bars: Bar[];
  unassigned: Bar[];
  availability: DayAvailability[];
  summary: {
    occupancy_percent: number;
    total_units: number;
    sold_units: number;
    out_of_order: number;
    arrivals_today: number;
    departures_today: number;
    in_house: number;
    unassigned_count: number;
  };
};
