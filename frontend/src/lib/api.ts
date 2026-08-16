/** طبقة الاتصال بالـ API — تحمل التوكن وتترجم الأخطاء للغتين. */

const TOKEN_KEY = "venicia.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  messageAr: string;
  messageEn: string;
  code?: string;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const d = detail as Record<string, unknown> | undefined;
    const ar = (d?.ar as string) || "حصل خطأ غير متوقع";
    const en = (d?.en as string) || "An unexpected error occurred";
    super(en);
    this.name = "ApiError";
    this.status = status;
    this.messageAr = ar;
    this.messageEn = en;
    this.code = d?.code as string | undefined;
    this.detail = detail;
  }

  text(locale: string) {
    return locale === "ar" ? this.messageAr : this.messageEn;
  }
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  form?: Record<string, string>;
  signal?: AbortSignal;
};

const BASE = "/api/v1";

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, form, signal } = options;
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload: BodyInit | undefined;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload, signal });

  if (res.status === 401) {
    setToken(null);
    // إعادة التوجيه لصفحة الدخول بدون كسر التطبيق. تطبيق الميدان ليه
    // شاشة دخول خاصة بيه — لو رمينا الهاوس كيبر على شاشة النظام
    // الكاملة هيلاقي نفسه في مكان تاني خالص وشغله في الطابور.
    const field = location.pathname.startsWith("/field");
    if (!field && !location.pathname.startsWith("/login")) location.href = "/login";
    throw new ApiError(401, { ar: "الجلسة انتهت", en: "Session expired" });
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const json = await res.json();
      detail = json?.detail ?? json;
    } catch {
      detail = null;
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T,>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });

/** بناء query string من كائن، مع تجاهل القيم الفاضية. */
export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}
