/** ألوان الحالات — مصدر واحد لكل الشاشات، مربوط بمتغيّرات الثيم. */

export const STATUS_COLOR: Record<string, string> = {
  CONFIRMED: "var(--st-confirmed)",
  CHECKED_IN: "var(--st-checkedin)",
  TENTATIVE: "var(--st-tentative)",
  CHECKED_OUT: "var(--st-checkedout)",
  CANCELLED: "var(--st-cancelled)",
  NO_SHOW: "var(--st-cancelled)",
};

export const HK_COLOR: Record<string, string> = {
  CLEAN: "var(--hk-clean)",
  DIRTY: "var(--hk-dirty)",
  CLEANING: "var(--hk-cleaning)",
  INSPECTED: "var(--hk-inspected)",
};

/** الحالات اللي بيتعرض معاها شريط على الشبكة */
export const LIVE_STATUSES = ["CONFIRMED", "CHECKED_IN", "TENTATIVE"] as const;

/** اختصار المصدر على الشريط — حرفين بيتقروا بسرعة */
export const SOURCE_SHORT: Record<string, string> = {
  BOOKING_COM: "BK",
  AGODA: "AG",
  EXPEDIA: "EX",
  AIRBNB: "AB",
  WEBSITE: "WEB",
  DIRECT: "DIR",
  WALK_IN: "WLK",
  TRAVEL_AGENT: "TA",
  CORPORATE: "CO",
  POS: "POS",
};

/** القنوات اللي بتاخد عمولة — بتتلوّن دهبي في الواجهة */
export const OTA_SOURCES = new Set(["BOOKING_COM", "AGODA", "EXPEDIA", "AIRBNB"]);
