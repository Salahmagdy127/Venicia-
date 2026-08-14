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

/* ────────────────────────────────── الإتاحة وحد التجاوز */
export type InventoryCategory = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  total_units: number;
};

export type InventoryCell = {
  unit_category_id: number;
  stay_date: string;
  total: number;
  out_of_order: number;
  sold: number;
  held: number;
  overbooking_limit: number;
  is_closed: boolean;
  available: number;
  oversold_by: number;
  occupancy_percent: number;
};

export type InventorySummary = {
  oversold_cells: number;
  closed_cells: number;
  limited_cells: number;
  sold_out_cells: number;
  waiting_count: number;
  offered_count: number;
  ready_count: number;
};

export type InventoryBoard = {
  start_date: string;
  end_date: string;
  categories: InventoryCategory[];
  cells: InventoryCell[];
  summary: InventorySummary;
};

export type ControlResult = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  rows_changed: number;
};

/* ─────────────────────────────────────────── قائمة الانتظار */
export type WaitlistStatus = "WAITING" | "OFFERED" | "CONVERTED" | "CANCELLED" | "EXPIRED";
export type WaitlistPriority = "NORMAL" | "HIGH" | "VIP";

export type WaitlistItem = {
  id: number;
  guest_id: number;
  guest_name: string;
  guest_phone: string | null;
  is_vip: boolean;
  unit_category_id: number;
  category_name_ar: string;
  category_name_en: string;
  rate_plan_id: number | null;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  flexible_days: number;
  status: WaitlistStatus;
  priority: WaitlistPriority;
  source: string;
  quoted_total: string;
  contact_note: string | null;
  offered_at: string | null;
  offer_expires_at: string | null;
  offered_arrival: string | null;
  offered_departure: string | null;
  converted_reservation_id: number | null;
  converted_reservation_code: string | null;
  created_at: string | null;
  has_match: boolean;
  match_arrival: string | null;
  match_departure: string | null;
  match_shift_days: number | null;
};

export type WaitlistPage = {
  items: WaitlistItem[];
  waiting_count: number;
  offered_count: number;
  ready_count: number;
};

export type WaitlistResult = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  entry: WaitlistItem | null;
  reservation_id: number | null;
  reservation_code: string | null;
};

/* ─────────────────────────────────────── الصيانة والميني بار */
export type TicketCategory =
  | "AC"
  | "PLUMBING"
  | "ELECTRICAL"
  | "FURNITURE"
  | "APPLIANCE"
  | "NETWORK"
  | "POOL"
  | "GROUNDS"
  | "OTHER";

export type TicketPriority = "LOW" | "NORMAL" | "HIGH" | "URGENT";
export type TicketStatus = "OPEN" | "ASSIGNED" | "IN_PROGRESS" | "DONE" | "CANCELLED";
export type TicketSource = "HOUSEKEEPING" | "GUEST" | "STAFF" | "INSPECTION";

export type Ticket = {
  id: number;
  number: string;
  unit_id: number | null;
  unit_label: string | null;
  location: string | null;
  category: TicketCategory;
  priority: TicketPriority;
  status: TicketStatus;
  source: TicketSource;
  title: string;
  description: string | null;
  blocks_unit: boolean;
  reported_by_name: string | null;
  assigned_to_user_id: number | null;
  assigned_to_name: string | null;
  folio_id: number | null;
  opened_at: string;
  assigned_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  due_at: string | null;
  is_overdue: boolean;
  resolution: string | null;
  cost: string;
  cancelled_reason: string | null;
};

export type MaintenanceBoard = {
  open: number;
  assigned: number;
  in_progress: number;
  done_today: number;
  overdue: number;
  urgent: number;
  blocked_units: number;
  cost_this_month: string;
  tickets: Ticket[];
};

export type Technician = {
  id: number;
  name_ar: string;
  name_en: string;
  role_ar: string;
};

export type MinibarItemOut = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  price: string;
  contains_alcohol: boolean;
};

/* ────────────────────────────────────── الفاتورة الإلكترونية */
export type EtaStatus =
  | "DRAFT"
  | "QUEUED"
  | "SUBMITTED"
  | "VALID"
  | "INVALID"
  | "REJECTED"
  | "CANCELLED"
  | "FAILED";

export type InvoiceKind = "INVOICE" | "RECEIPT" | "CREDIT_NOTE" | "DEBIT_NOTE";

export type InvoiceLineOut = {
  line_number: number;
  description_ar: string;
  description_en: string | null;
  item_code: string | null;
  unit_type: string;
  quantity: string;
  unit_price: string;
  sales_total: string;
  discount_amount: string;
  net_total: string;
  tax_percent: string;
  tax_amount: string;
  service_charge_amount: string;
  total: string;
};

export type InvoiceDetail = {
  id: number;
  number: string;
  invoice_type: InvoiceKind;
  business_date: string;
  issued_at: string;
  folio_id: number | null;
  pos_order_id: number | null;
  reservation_id: number | null;
  customer_name: string;
  customer_tax_number: string | null;
  customer_national_id: string | null;
  customer_type: string;
  currency: string;
  subtotal: string;
  discount_total: string;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  eta_status: EtaStatus;
  eta_uuid: string | null;
  eta_internal_id: string | null;
  eta_error_message: string | null;
  eta_retry_count: number;
  eta_submitted_at: string | null;
  eta_accepted_at: string | null;
  qr_payload: string | null;
  is_cancelled: boolean;
  cancellation_reason: string | null;
  credit_note_for_invoice_id: number | null;
  lines: InvoiceLineOut[];
};

export type InvoiceListItem = {
  id: number;
  number: string;
  invoice_type: InvoiceKind;
  business_date: string;
  issued_at: string;
  customer_name: string;
  grand_total: string;
  tax_total: string;
  eta_status: EtaStatus;
  is_cancelled: boolean;
  eta_error_message: string | null;
};

export type InvoiceStats = {
  total: number;
  accepted: number;
  pending: number;
  failed: number;
  rejected: number;
  draft: number;
  cancelled: number;
  today_total: string;
  today_tax: string;
  eta_enabled: boolean;
};

export type QueueResult = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  accepted: number;
  failed: number;
  requeued: number;
};

/* ───────────────────────────────────────── الحجز المباشر */
export type PublicCategory = {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  kind: string;
  base_occupancy: number;
  max_occupancy: number;
  area_sqm: number | null;
  bed_configuration: string | null;
  amenities_ar: string | null;
  amenities_en: string | null;
  from_rate: string;
  unit_count: number;
};

export type PublicProperty = {
  name_ar: string;
  name_en: string;
  city: string | null;
  address: string | null;
  phone: string | null;
  email: string | null;
  currency: string;
  check_in_time: string;
  check_out_time: string;
  vat_percent: string;
  service_charge_percent: string;
  categories: PublicCategory[];
};

export type PublicOffer = {
  unit_category_id: number;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  kind: string;
  max_occupancy: number;
  area_sqm: number | null;
  bed_configuration: string | null;
  amenities_ar: string | null;
  amenities_en: string | null;
  nights: number;
  room_total: string;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  average_nightly_rate: string;
  left: number;
  nights_detail: { stay_date: string; rate: string }[];
};

export type SearchOut = {
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  currency: string;
  offers: PublicOffer[];
};

export type HoldOut = {
  token: string;
  expires_at: string;
  hold_minutes: number;
  unit_category_id: number;
  name_ar: string;
  name_en: string;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  room_total: string;
  service_charge_total: string;
  tax_total: string;
  grand_total: string;
  deposit_required: string;
};

export type BookingOut = {
  code: string;
  status: string;
  guest_name: string;
  arrival_date: string;
  departure_date: string;
  nights: number;
  adults: number;
  children: number;
  category_name_ar: string;
  category_name_en: string;
  grand_total: string;
  paid_total: string;
  balance: string;
  check_in_time: string;
  check_out_time: string;
  special_requests: string | null;
};

/* ────────────────────────────────────────── الربط بالقنوات */
export type ChannelMapping = {
  id: number;
  unit_category_id: number;
  category_name_ar: string;
  category_name_en: string;
  rate_plan_id: number | null;
  rate_plan_name_ar: string | null;
  external_room_id: string;
  external_rate_id: string | null;
  allocation: number;
  is_active: boolean;
};

export type Channel = {
  id: number;
  source: string;
  name_ar: string;
  name_en: string;
  is_active: boolean;
  is_connected: boolean;
  commission_percent: string;
  external_property_id: string | null;
  last_push_at: string | null;
  last_pull_at: string | null;
  pushed_count: number;
  pulled_count: number;
  error_count: number;
  last_error: string | null;
  pending: number;
  failed: number;
  sent_today: number;
  mapped_categories: number;
  bookings_today: number;
  rejected_today: number;
  mappings: ChannelMapping[];
};

export type ChannelBoard = {
  channels: Channel[];
  total_pending: number;
  total_failed: number;
  unmapped_categories: number[];
};

export type ChannelMessageKind = "AVAILABILITY" | "RATE" | "STOP_SELL";
export type ChannelMessageStatus = "PENDING" | "SENT" | "FAILED" | "SKIPPED";

export type ChannelMessage = {
  id: number;
  channel_id: number;
  channel_source: string;
  unit_category_id: number | null;
  category_name_ar: string | null;
  kind: ChannelMessageKind;
  status: ChannelMessageStatus;
  start_date: string;
  end_date: string;
  reason: string | null;
  attempts: number;
  created_at: string;
  sent_at: string | null;
  error: string | null;
};

export type ChannelBookingAction = "NEW" | "MODIFY" | "CANCEL";
export type ChannelBookingStatus = "PROCESSED" | "DUPLICATE" | "REJECTED" | "FAILED";

export type ChannelBookingRow = {
  id: number;
  channel_id: number;
  channel_source: string;
  external_reference: string;
  action: ChannelBookingAction;
  status: ChannelBookingStatus;
  guest_name: string | null;
  guest_phone: string | null;
  arrival_date: string | null;
  departure_date: string | null;
  gross_amount: string;
  commission_amount: string;
  reservation_id: number | null;
  reservation_code: string | null;
  error: string | null;
  received_at: string;
};

export type SyncResult = {
  ok: boolean;
  message_ar: string;
  message_en: string;
  sent: number;
  failed: number;
  skipped: number;
  queued: number;
};

/* ───────────────────────────────────────────── تدقيق الليلة */
export type AuditWarnings = {
  open_folios: number;
  open_pos_orders: number;
  open_shifts: number;
  in_house_without_unit: number;
  overdue_checkouts: number;
  oversold_days: number;
  waitlist_ready: number;
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
