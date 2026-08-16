/**
 * قاعدة البيانات المحلية على التليفون — IndexedDB.
 *
 * التطبيق بيقرا **من هنا** دايماً، مش من الشبكة. الشبكة مجرد وسيلة
 * لمزامنة المحتوى ده مع السيرفر لما تكون موجودة.
 *
 * أربع مخازن:
 *   state   — آخر نسخة من الجولة والحزمة الأساسية
 *   queue   — العمليات اللي لسه ماوصلتش السيرفر
 *   photos  — بايتس الصور المستنية الرفع (Blob جوّه IndexedDB)
 *   log     — آخر ٢٠٠ حدث، عشان الموظف يقدر يثبت إنه عمل الشغل
 *
 * ليه IndexedDB مش localStorage؟ لأن الصور Blob، وlocalStorage نص بس
 * وحجمه ٥ ميجا. جولة يوم واحدة فيها ٤٠ صورة — يعني localStorage
 * كان هيقع من أول ساعة.
 */

const DB_NAME = "venicia-field";
const DB_VERSION = 1;

export type StoreName = "state" | "queue" | "photos" | "log";

let handle: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (handle) return handle;
  handle = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("state")) db.createObjectStore("state");
      if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "uuid" });
      if (!db.objectStoreNames.contains("photos")) db.createObjectStore("photos", { keyPath: "uuid" });
      if (!db.objectStoreNames.contains("log")) db.createObjectStore("log", { autoIncrement: true });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return handle;
}

function run<T>(
  store: StoreName,
  mode: IDBTransactionMode,
  action: (s: IDBObjectStore) => IDBRequest,
): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(store, mode);
        const request = action(tx.objectStore(store));
        request.onsuccess = () => resolve(request.result as T);
        request.onerror = () => reject(request.error);
      }),
  );
}

export const kv = {
  get: <T,>(key: string) => run<T | undefined>("state", "readonly", (s) => s.get(key)),
  set: <T,>(key: string, value: T) =>
    run<IDBValidKey>("state", "readwrite", (s) => s.put(value, key)),
  remove: (key: string) => run<undefined>("state", "readwrite", (s) => s.delete(key)),
};

export const queue = {
  all: <T,>() => run<T[]>("queue", "readonly", (s) => s.getAll()),
  put: <T,>(item: T) => run<IDBValidKey>("queue", "readwrite", (s) => s.put(item)),
  remove: (uuid: string) => run<undefined>("queue", "readwrite", (s) => s.delete(uuid)),
  clear: () => run<undefined>("queue", "readwrite", (s) => s.clear()),
};

export const photos = {
  all: <T,>() => run<T[]>("photos", "readonly", (s) => s.getAll()),
  put: <T,>(item: T) => run<IDBValidKey>("photos", "readwrite", (s) => s.put(item)),
  remove: (uuid: string) => run<undefined>("photos", "readwrite", (s) => s.delete(uuid)),
  get: <T,>(uuid: string) => run<T | undefined>("photos", "readonly", (s) => s.get(uuid)),
};

/** معرّف فريد للعملية — بيتولّد على التليفون قبل أي محاولة إرسال. */
export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * معرّف الجهاز — بيتخزّن مرة وبيفضل.
 *
 * فايدته إن السجل يقدر يقول «الغرفة دي اتصوّرت من تليفون رقم كام»،
 * وده بيفرق لما تليفون يضيع أو حد يشتكي إن حد تاني قفل مهمته.
 */
export function deviceId(): string {
  const key = "venicia.field.device";
  let value = localStorage.getItem(key);
  if (!value) {
    value = newId();
    localStorage.setItem(key, value);
  }
  return value;
}
