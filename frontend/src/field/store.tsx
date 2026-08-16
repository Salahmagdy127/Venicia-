/**
 * محرّك التطبيق الميداني — الحالة المحلية والمزامنة.
 *
 * القاعدة الوحيدة اللي كل حاجة هنا مبنية عليها:
 * **الضغطة بتتنفّذ على التليفون فوراً، والشبكة تلحق بعدين.**
 *
 * لما الهاوس كيبر يضغط «خلصت»:
 *   ١. الحالة المحلية بتتغيّر في نفس اللحظة — الكارت بيقفل قدام عينه.
 *   ٢. العملية بتتكتب في طابور على القرص بمعرّف اتولّد دلوقتي.
 *   ٣. لو فيه شبكة بتتبعت. لو مفيش، بتفضل في الطابور.
 *   ٤. لما الشبكة ترجع، الطابور بيتبعت كله في طلب واحد.
 *   ٥. السيرفر بيرد على كل عملية لوحدها. اللي اتنفّذ أو اتكرّر بيتمسح
 *      من الطابور. اللي اترفض بيتعرض للموظف. اللي فشل فنياً بيفضل
 *      للمحاولة الجاية.
 *
 * والمعرّف هو اللي بيخلّي الخطوة ٤ آمنة: لو الرد ضاع بعد ما السيرفر
 * نفّذ، الإرسال التاني بيرجع ``DUPLICATE`` مش بينفّذ تاني.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api, get, getToken, post, setToken } from "@/lib/api";
import { deviceId, kv, newId, photos as photoStore, queue } from "./db";
import type {
  Board,
  Bootstrap,
  PhotoPhase,
  QueuedAction,
  QueuedPhoto,
  SyncResponse,
  SyncResult,
  Task,
} from "./types";

const BOARD_KEY = "board";
const BOOT_KEY = "bootstrap";

export type Toast = {
  id: string;
  tone: "good" | "warn" | "bad" | "info";
  text: string;
  detail?: string;
};

type Ctx = {
  ready: boolean;
  authed: boolean;
  board: Board | null;
  boot: Bootstrap | null;
  online: boolean;
  syncing: boolean;
  pending: number;
  pendingPhotos: number;
  lastSync: string | null;
  /** آخر مرة نزلت فيها الجولة من السيرفر — بيبان في الهيدر */
  stale: boolean;
  toasts: Toast[];
  dismiss: (id: string) => void;
  notify: (t: Omit<Toast, "id">) => void;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  flush: () => Promise<void>;
  act: (
    type: string,
    options: {
      taskId?: number;
      ticketId?: number;
      payload?: Record<string, unknown>;
    },
  ) => Promise<void>;
  capture: (taskId: number, phase: PhotoPhase, blob: Blob) => Promise<void>;
  /** الصور اللي لسه على التليفون — معروضة قبل ما ترفع */
  localPhotos: Record<number, { uuid: string; phase: PhotoPhase; url: string }[]>;
};

const FieldContext = createContext<Ctx | null>(null);

// ═══════════════════════════════════════════ التطبيق المحلي للعمليات
/**
 * بيطبّق العملية على النسخة المحلية بنفس قواعد السيرفر.
 *
 * لازم القواعد تتكرّر هنا — مش تكرار زيادة: التليفون بيشتغل ساعات من
 * غير شبكة، والموظف لازم يشوف نتيجة صح طول الوقت. السيرفر بيفضل هو
 * الحكم الأخير، وأي اختلاف بيتصلّح أول مزامنة.
 */
function applyLocally(board: Board, action: QueuedAction): Board {
  const at = action.at;
  const tasks = board.tasks.map((task): Task => {
    if (task.id !== action.task_id) return task;
    switch (action.type) {
      case "task.start":
        return {
          ...task,
          status: "IN_PROGRESS",
          started_at: task.started_at ?? at,
          snoozed_until: null,
        };
      case "task.complete":
        return {
          ...task,
          status: "DONE",
          completed_at: at,
          started_at: task.started_at ?? at,
          linen_changed: Boolean(action.payload.linen_changed),
          amenities_restocked: Boolean(action.payload.amenities_restocked),
          minibar_checked: Boolean(action.payload.minibar_checked),
          note: (action.payload.note as string) || task.note,
          working_seconds:
            task.working_seconds ||
            Math.max(
              0,
              Math.round(
                (new Date(at).getTime() -
                  new Date(task.started_at ?? at).getTime()) /
                  1000,
              ),
            ),
        };
      case "task.dnd": {
        const minutes = Number(action.payload.snooze_minutes ?? 60);
        return {
          ...task,
          status: "DND",
          dnd_attempts: task.dnd_attempts + 1,
          snoozed_until: new Date(
            new Date(at).getTime() + minutes * 60_000,
          ).toISOString(),
        };
      }
      case "task.block":
        return {
          ...task,
          status: "BLOCKED",
          blocked_reason: (action.payload.reason as string) || null,
        };
      case "task.skip":
        return { ...task, status: "SKIPPED" };
      case "task.note":
        return { ...task, note: (action.payload.note as string) || task.note };
      case "task.minibar":
        return { ...task, minibar_checked: true };
      case "task.inspect": {
        const score = Number(action.payload.score ?? 5);
        return {
          ...task,
          status: score >= 3 ? "INSPECTED" : "REJECTED",
          inspection_score: score,
          inspection_note: (action.payload.note as string) || null,
        };
      }
      default:
        return task;
    }
  });

  const closed = new Set(["DONE", "INSPECTED", "SKIPPED"]);
  const done = tasks.filter((t) => closed.has(t.status)).length;
  return { ...board, tasks, done, remaining: tasks.length - done };
}

function bumpPhoto(board: Board, taskId: number, phase: PhotoPhase): Board {
  return {
    ...board,
    tasks: board.tasks.map((task) =>
      task.id === taskId
        ? {
            ...task,
            photo_before_count:
              task.photo_before_count + (phase === "BEFORE" ? 1 : 0),
            photo_after_count: task.photo_after_count + (phase === "AFTER" ? 1 : 0),
          }
        : task,
    ),
  };
}

// ═══════════════════════════════════════════════════════════ المزوّد
export function FieldProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [board, setBoard] = useState<Board | null>(null);
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [syncing, setSyncing] = useState(false);
  const [pending, setPending] = useState(0);
  const [pendingPhotos, setPendingPhotos] = useState(0);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [localPhotos, setLocalPhotos] = useState<Ctx["localPhotos"]>({});
  const flushing = useRef(false);
  const urls = useRef<string[]>([]);

  const notify = useCallback((toast: Omit<Toast, "id">) => {
    const id = newId();
    setToasts((list) => [...list, { ...toast, id }]);
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 4200);
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const counters = useCallback(async () => {
    const [q, p] = await Promise.all([
      queue.all<QueuedAction>(),
      photoStore.all<QueuedPhoto>(),
    ]);
    setPending(q.length);
    setPendingPhotos(p.length);
    // معاينات الصور المحلية — قبل ما ترفع الموظف لازم يشوف اللي صوّره
    const map: Ctx["localPhotos"] = {};
    urls.current.forEach((u) => URL.revokeObjectURL(u));
    urls.current = [];
    for (const photo of p) {
      if (photo.task_id == null) continue;
      const url = URL.createObjectURL(photo.blob);
      urls.current.push(url);
      (map[photo.task_id] ??= []).push({
        uuid: photo.uuid,
        phase: photo.phase,
        url,
      });
    }
    setLocalPhotos(map);
  }, []);

  // ── أول تشغيل: بنقرا من القرص قبل أي طلب شبكة ────────────────────
  useEffect(() => {
    (async () => {
      const [cachedBoard, cachedBoot] = await Promise.all([
        kv.get<Board>(BOARD_KEY),
        kv.get<Bootstrap>(BOOT_KEY),
      ]);
      if (cachedBoard) setBoard(cachedBoard);
      if (cachedBoot) setBoot(cachedBoot);
      setLastSync(localStorage.getItem("venicia.field.lastSync"));
      await counters();
      setReady(true);
    })();
    return () => urls.current.forEach((u) => URL.revokeObjectURL(u));
  }, [counters]);

  const saveBoard = useCallback(async (next: Board) => {
    setBoard(next);
    await kv.set(BOARD_KEY, next);
  }, []);

  /**
   * بيحط اللي لسه في الطابور فوق نسخة السيرفر.
   *
   * الصور اللي لسه ما اترفعتش بتتعدّ برضه: من غير كده الموظف بيصوّر
   * «بعد»، تحصل مزامنة نص كام، وزرار «خلصت» يقفل في وشه — والصورة
   * موجودة على تليفونه قدامه.
   */
  const rebase = useCallback(async (server: Board): Promise<Board> => {
    const [actions, waitingPhotos] = await Promise.all([
      queue.all<QueuedAction>(),
      photoStore.all<QueuedPhoto>(),
    ]);
    let next = [...actions]
      .sort((a, b) => a.at.localeCompare(b.at))
      .reduce((board, action) => applyLocally(board, action), server);
    for (const photo of waitingPhotos) {
      if (photo.task_id != null) next = bumpPhoto(next, photo.task_id, photo.phase);
    }
    return next;
  }, []);

  // ── تنزيل الجولة من السيرفر ──────────────────────────────────────
  const refresh = useCallback(async () => {
    if (!getToken()) return;
    const fresh = await get<Board>("/field/board");
    await saveBoard(await rebase(fresh));
    const stamp = new Date().toISOString();
    localStorage.setItem("venicia.field.lastSync", stamp);
    setLastSync(stamp);
    const version = boot?.version;
    const pack = await get<Bootstrap>("/field/bootstrap");
    if (pack.version !== version) {
      setBoot(pack);
      await kv.set(BOOT_KEY, pack);
    }
  }, [boot?.version, rebase, saveBoard]);

  // ── رفع الصور المستنية ───────────────────────────────────────────
  const flushPhotos = useCallback(async (): Promise<number> => {
    const waiting = await photoStore.all<QueuedPhoto>();
    let uploaded = 0;
    for (const photo of waiting) {
      const form = new FormData();
      form.append("file", photo.blob, `${photo.uuid}.jpg`);
      form.append("client_uuid", photo.uuid);
      form.append("phase", photo.phase);
      form.append("taken_at", photo.taken_at);
      form.append("device_id", deviceId());
      if (photo.task_id != null) form.append("task_id", String(photo.task_id));
      if (photo.ticket_id != null) form.append("ticket_id", String(photo.ticket_id));
      if (photo.note) form.append("note", photo.note);

      try {
        const res = await fetch("/api/v1/field/photos", {
          method: "POST",
          headers: { Authorization: `Bearer ${getToken()}` },
          body: form,
        });
        if (res.ok) {
          await photoStore.remove(photo.uuid);
          uploaded += 1;
        } else if (res.status === 400 || res.status === 404) {
          // الصورة نفسها مرفوضة — إعادة المحاولة مش هتغيّر حاجة.
          // بنشيلها عشان متفضلش تعطّل الطابور للأبد.
          await photoStore.remove(photo.uuid);
        } else {
          await photoStore.put({ ...photo, attempts: photo.attempts + 1 });
          break; // الشبكة تعبانة — نوقف ونجرّب تاني بعدين
        }
      } catch {
        await photoStore.put({ ...photo, attempts: photo.attempts + 1 });
        break;
      }
    }
    return uploaded;
  }, []);

  // ── إرسال الطابور ────────────────────────────────────────────────
  const flush = useCallback(async () => {
    if (flushing.current || !getToken()) return;
    flushing.current = true;
    setSyncing(true);
    try {
      // الصور الأول: عملية «خلصت» بترفض من السيرفر لو صورة البعد
      // ماوصلتش. الترتيب ده هو اللي بيمنع رفض متكرّر بلا سبب.
      await flushPhotos();

      const waiting = (await queue.all<QueuedAction>()).sort(
        (a, b) => a.at.localeCompare(b.at),
      );
      if (waiting.length) {
        const response = await post<SyncResponse>("/field/sync", {
          device_id: deviceId(),
          actions: waiting.map((a) => ({
            uuid: a.uuid,
            type: a.type,
            task_id: a.task_id ?? null,
            ticket_id: a.ticket_id ?? null,
            at: a.at,
            payload: a.payload,
          })),
        });

        const problems: SyncResult[] = [];
        for (const result of response.results) {
          if (result.outcome === "APPLIED" || result.outcome === "DUPLICATE") {
            await queue.remove(result.uuid);
          } else if (result.outcome === "FAILED") {
            const item = waiting.find((a) => a.uuid === result.uuid);
            if (item) {
              // بعد ٥ محاولات فاشلة بنسيبها — الاحتفاظ بيها للأبد
              // بيخلّي كل مزامنة بعدين تفشل معاها
              if (item.attempts >= 5) {
                await queue.remove(item.uuid);
                problems.push(result);
              } else {
                await queue.put({ ...item, attempts: item.attempts + 1 });
              }
            }
          } else {
            await queue.remove(result.uuid);
            problems.push(result);
          }
        }

        // لوحة السيرفر بتحل محل النسخة المحلية — بس اللي لسه في الطابور
        // لازم يتحطّ فوقها تاني. من غير الخطوة دي، عملية فشلت فنياً
        // وفضلت في الطابور بيرجع الكارت بتاعها لحالته القديمة قدام
        // الموظف، وهو عارف إنه عملها. فبيعملها تاني.
        await saveBoard(await rebase(response.board));
        if (problems.length) {
          notify({
            tone: "warn",
            text: `${problems.length} عملية اترفضت`,
            detail: problems[0].message_ar ?? undefined,
          });
        } else if (response.applied) {
          notify({ tone: "good", text: `${response.applied} عملية اتزامنت` });
        }
      } else {
        await refresh();
      }

      const stamp = new Date().toISOString();
      localStorage.setItem("venicia.field.lastSync", stamp);
      setLastSync(stamp);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuthed(false);
      }
      // أي خطأ تاني معناه الشبكة — الطابور مكانه وهيتبعت بعدين
    } finally {
      await counters();
      setSyncing(false);
      flushing.current = false;
    }
  }, [counters, flushPhotos, notify, rebase, refresh, saveBoard]);

  // ── تسجيل عملية ──────────────────────────────────────────────────
  const act = useCallback<Ctx["act"]>(
    async (type, options) => {
      const action: QueuedAction = {
        uuid: newId(),
        type,
        task_id: options.taskId ?? null,
        ticket_id: options.ticketId ?? null,
        at: new Date().toISOString(),
        payload: options.payload ?? {},
        attempts: 0,
      };

      if (board && action.task_id) {
        await saveBoard(applyLocally(board, action));
      }
      await queue.put(action);
      await counters();
      void flush();
    },
    [board, counters, flush, saveBoard],
  );

  // ── تصوير ────────────────────────────────────────────────────────
  const capture = useCallback<Ctx["capture"]>(
    async (taskId, phase, blob) => {
      const photo: QueuedPhoto = {
        uuid: newId(),
        task_id: taskId,
        ticket_id: null,
        phase,
        taken_at: new Date().toISOString(),
        blob,
        attempts: 0,
      };
      await photoStore.put(photo);
      if (board) await saveBoard(bumpPhoto(board, taskId, phase));
      await counters();
      void flush();
    },
    [board, counters, flush, saveBoard],
  );

  // ── الدخول والخروج ───────────────────────────────────────────────
  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        form: { username, password },
      });
      setToken(res.access_token);
      setAuthed(true);
      await refresh();
      await flush();
    },
    [flush, refresh],
  );

  const logout = useCallback(() => {
    setToken(null);
    setAuthed(false);
    setBoard(null);
    void kv.remove(BOARD_KEY);
  }, []);

  // ── مراقبة الشبكة ────────────────────────────────────────────────
  useEffect(() => {
    const up = () => {
      setOnline(true);
      void flush();
    };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    // ولو التطبيق رجع للواجهة بعد ما كان في الخلفية
    const visible = () => {
      if (document.visibilityState === "visible" && navigator.onLine) void flush();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [flush]);

  // مزامنة دورية خفيفة — كل دقيقتين لو فيه شبكة وحاجة مستنية
  useEffect(() => {
    const timer = setInterval(() => {
      if (navigator.onLine && getToken()) void flush();
    }, 120_000);
    return () => clearInterval(timer);
  }, [flush]);

  // أول تحميل بعد الجاهزية: لو فيه توكن، نزّل الجولة
  useEffect(() => {
    if (!ready || !authed) return;
    void flush();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, authed]);

  const stale = useMemo(() => {
    if (!lastSync) return true;
    return Date.now() - new Date(lastSync).getTime() > 30 * 60_000;
  }, [lastSync]);

  const value = useMemo<Ctx>(
    () => ({
      ready, authed, board, boot, online, syncing, pending, pendingPhotos,
      lastSync, stale, toasts, dismiss, notify, login, logout, refresh, flush,
      act, capture, localPhotos,
    }),
    [
      ready, authed, board, boot, online, syncing, pending, pendingPhotos,
      lastSync, stale, toasts, dismiss, notify, login, logout, refresh, flush,
      act, capture, localPhotos,
    ],
  );

  return <FieldContext.Provider value={value}>{children}</FieldContext.Provider>;
}

export function useField() {
  const ctx = useContext(FieldContext);
  if (!ctx) throw new Error("useField must be used inside FieldProvider");
  return ctx;
}
