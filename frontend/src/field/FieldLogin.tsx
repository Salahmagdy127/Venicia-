/**
 * دخول تطبيق الميدان.
 *
 * شاشة واحدة وخانتين. مفيش «تذكرني» لأن الدخول بيفضل شغّال، ومفيش
 * اختيار لغة لأن الفريق بيتكلّم عربي. أقل عدد قرارات ممكن قبل ما
 * الموظف يشوف شغله.
 */

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useField } from "./store";
import { Mark } from "./icons";

export default function FieldLogin() {
  const { login } = useField();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (problem) {
      if (problem instanceof ApiError) setError(problem.messageAr);
      else setError("مش قادر أوصل للسيرفر — اتأكد من الشبكة");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="f-login">
      <div style={{ color: "var(--f-accent)" }}>
        <Mark size={68} className="f-login-mark" />
      </div>
      <h1>فينيسيا</h1>
      <p>
        سجّل دخولك مرة واحدة. بعد كده التطبيق بيشتغل من غير شبكة، وشغلك
        بيوصل لوحده أول ما تلاقي إشارة.
      </p>

      <form onSubmit={submit}>
        <input
          className="f-input"
          placeholder="اسم المستخدم"
          value={username}
          autoCapitalize="none"
          autoCorrect="off"
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          className="f-input"
          type="password"
          placeholder="كلمة السر"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error ? <div className="f-error">{error}</div> : null}
        <button
          className="f-btn is-primary is-wide"
          type="submit"
          disabled={busy || !username || !password}
          style={{ marginTop: 6 }}
        >
          {busy ? "بيدخل…" : "ادخل"}
        </button>
      </form>
    </div>
  );
}
