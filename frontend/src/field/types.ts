/** أنواع تطبيق الميدان — نفس عقد الـ API بالحرف. */

export type TaskKind =
  | "DEPARTURE"
  | "ARRIVAL_PREP"
  | "STAYOVER"
  | "TURNDOWN"
  | "DEEP"
  | "POST_MAINTENANCE"
  | "INSPECTION";

export type TaskStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "DND"
  | "BLOCKED"
  | "DONE"
  | "INSPECTED"
  | "REJECTED"
  | "SKIPPED";

export type PhotoPhase = "BEFORE" | "AFTER" | "ISSUE" | "MINIBAR";

export type SyncOutcome = "APPLIED" | "DUPLICATE" | "CONFLICT" | "REJECTED" | "FAILED";

export type FieldPhoto = {
  id: number;
  phase: PhotoPhase;
  url: string;
  thumb_url: string | null;
  taken_at: string;
  taken_by_name: string | null;
  note: string | null;
};

export type Task = {
  id: number;
  unit_id: number;
  unit_label: string;
  zone_ar: string | null;
  zone_en: string | null;
  category_name_ar: string;
  category_name_en: string;
  task_date: string;
  kind: TaskKind;
  status: TaskStatus;
  priority: number;
  expected_minutes: number;
  working_seconds: number;
  photos_required: boolean;
  photo_before_count: number;
  photo_after_count: number;
  dnd_attempts: number;
  snoozed_until: string | null;
  blocked_reason: string | null;
  started_at: string | null;
  completed_at: string | null;
  linen_changed: boolean;
  amenities_restocked: boolean;
  minibar_checked: boolean;
  inspection_score: number | null;
  inspection_note: string | null;
  note: string | null;
  assigned_to_user_id: number | null;
  assigned_to_name: string | null;
  ticket_id: number | null;
  has_minibar: boolean;
  is_occupied: boolean;
  photos: FieldPhoto[];
};

export type FieldTicket = {
  id: number;
  number: string;
  unit_id: number | null;
  unit_label: string | null;
  location: string | null;
  category: string;
  priority: string;
  status: string;
  title: string;
  description: string | null;
  blocks_unit: boolean;
  opened_at: string;
  due_at: string | null;
  is_overdue: boolean;
  is_mine: boolean;
};

export type Board = {
  business_date: string;
  server_time: string;
  user_id: number;
  user_name_ar: string;
  user_name_en: string;
  role_ar: string;
  role_en: string;
  can_clean: boolean;
  can_fix: boolean;
  can_inspect: boolean;
  tasks: Task[];
  tickets: FieldTicket[];
  done: number;
  remaining: number;
  minutes_planned: number;
  minutes_worked: number;
};

export type Label = { code: string; name_ar: string; name_en: string };

export type Bootstrap = {
  version: string;
  server_time: string;
  property_id: number;
  property_name_ar: string;
  property_name_en: string;
  units: {
    id: number;
    label: string;
    zone_ar: string | null;
    zone_en: string | null;
    building: string | null;
    category_name_ar: string;
    category_name_en: string;
    has_minibar: boolean;
  }[];
  minibar: {
    id: number;
    code: string;
    name_ar: string;
    name_en: string;
    price: string;
    contains_alcohol: boolean;
  }[];
  ticket_categories: Label[];
  ticket_priorities: Label[];
  task_kinds: Label[];
  block_reasons: Label[];
  dnd_snooze_minutes: number;
  dnd_escalate_after: number;
};

/** عملية في الطابور المحلي — بتتخزّن على التليفون لحد ما توصل. */
export type QueuedAction = {
  uuid: string;
  type: string;
  task_id?: number | null;
  ticket_id?: number | null;
  at: string;
  payload: Record<string, unknown>;
  /** كام مرة حاولنا نبعتها — بيستخدم في التراجع التدريجي */
  attempts: number;
  /** آخر رفض من السيرفر، عشان الموظف يشوفه */
  error?: string | null;
};

/** صورة مستنية الرفع — البايتس نفسها متخزّنة في IndexedDB. */
export type QueuedPhoto = {
  uuid: string;
  task_id: number | null;
  ticket_id: number | null;
  phase: PhotoPhase;
  taken_at: string;
  blob: Blob;
  attempts: number;
  note?: string | null;
};

export type SyncResult = {
  uuid: string;
  type: string;
  outcome: SyncOutcome;
  task_id: number | null;
  ticket_id: number | null;
  status: string | null;
  message_ar: string | null;
  message_en: string | null;
  code: string | null;
};

export type SyncResponse = {
  server_time: string;
  applied: number;
  duplicates: number;
  rejected: number;
  results: SyncResult[];
  board: Board;
};
