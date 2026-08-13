import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { ApiError } from "@/lib/api";
import { Button, inputClass } from "@/components/ui";
import { IconWaves } from "@/components/Icons";
import { TopBarToggles } from "@/components/Layout";

const DEMO = [
  { user: "owner", ar: "المالك", en: "Owner" },
  { user: "nourhan", ar: "مدير استقبال", en: "Front office manager" },
  { user: "ahmed", ar: "استقبال", en: "Front desk" },
  { user: "tarek", ar: "مدير مطعم", en: "Restaurant manager" },
  { user: "sayed", ar: "كاشير", en: "Cashier" },
  { user: "samia", ar: "هاوس كيبينج", en: "Housekeeping" },
];

export default function Login() {
  const { t, locale } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("owner");
  const [password, setPassword] = useState("venicia2026");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.text(locale) : t("login.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="h-screen w-screen flex overflow-hidden">
      {/* اللوحة الجانبية — هوية المكان */}
      <div className="hidden md:flex w-[46%] bg-sidebar text-sidebar-ink flex-col justify-between p-12">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-[10px] bg-white/10 grid place-items-center">
            <IconWaves size={24} className="text-white" />
          </span>
          <div>
            <div className="text-[22px] font-bold text-white leading-tight">
              {t("app.name")}
            </div>
            <div className="text-[13px] opacity-70">{t("app.tagline")}</div>
          </div>
        </div>

        <div className="max-w-[36ch]">
          <p className="text-[26px] font-bold leading-snug text-white mb-3">
            {locale === "ar"
              ? "كل جنيه في القرية بيعدّي من نقطة واحدة."
              : "Every pound in the resort passes through one place."}
          </p>
          <p className="text-[14px] opacity-70 leading-relaxed">
            {locale === "ar"
              ? "الحجوزات · نقاط البيع · حساب النزيل · التقارير — نظام واحد."
              : "Reservations · point of sale · guest folio · reporting — one system."}
          </p>
        </div>

        <div className="text-[12px] opacity-45 num">Venicia Resort Suite · v0.1</div>
      </div>

      {/* نموذج الدخول */}
      <div className="flex-1 bg-ground flex flex-col">
        <div className="flex justify-end p-4">
          <TopBarToggles />
        </div>

        <div className="flex-1 grid place-items-center px-6 pb-16 overflow-y-auto">
          <div className="w-full max-w-[380px]">
            <h1 className="text-[26px] font-bold mb-1">{t("login.title")}</h1>
            <p className="text-[14px] text-muted mb-7">{t("app.tagline")}</p>

            <form onSubmit={submit}>
              <label className="flex flex-col gap-1.5 mb-4">
                <span className="text-[13px] font-bold text-ink-2">{t("login.username")}</span>
                <input
                  className={`${inputClass} mono`}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </label>

              <label className="flex flex-col gap-1.5 mb-5">
                <span className="text-[13px] font-bold text-ink-2">{t("login.password")}</span>
                <input
                  className={`${inputClass} mono`}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </label>

              {error && (
                <div className="mb-4 rounded-[6px] border border-bad/40 bg-bad/10 text-bad text-[13px] px-3.5 py-2.5">
                  {error}
                </div>
              )}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                className="w-full"
                disabled={busy || !username || !password}
              >
                {busy ? "…" : t("login.submit")}
              </Button>
            </form>

            <div className="mt-9 pt-5 border-t border-line">
              <div className="text-[12px] font-bold text-muted mb-2.5">{t("login.demo")}</div>
              <div className="flex flex-wrap gap-1.5">
                {DEMO.map((d) => (
                  <button
                    key={d.user}
                    type="button"
                    onClick={() => {
                      setUsername(d.user);
                      setPassword("venicia2026");
                    }}
                    className="text-[12px] rounded-full border border-line px-2.5 py-1 hover:bg-surface-2 text-ink-2"
                  >
                    {locale === "ar" ? d.ar : d.en}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
