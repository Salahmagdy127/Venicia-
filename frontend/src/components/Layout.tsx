import { NavLink, Outlet } from "react-router-dom";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { cx } from "./ui";
import {
  IconBroom,
  IconCalendar,
  IconChart,
  IconDashboard,
  IconGlobe,
  IconGrid,
  IconGuests,
  IconLink,
  IconLogout,
  IconReceipt,
  IconMoon,
  IconArrows,
  IconPos,
  IconSettings,
  IconSun,
  IconWaves,
} from "./Icons";

type NavItem = {
  to: string;
  labelKey: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  permission?: string;
};

const NAV: NavItem[] = [
  { to: "/", labelKey: "nav.dashboard", icon: IconDashboard },
  { to: "/tape-chart", labelKey: "nav.tapechart", icon: IconCalendar, permission: "reservation.view" },
  { to: "/front-desk", labelKey: "nav.frontdesk", icon: IconArrows, permission: "reservation.view" },
  { to: "/inventory", labelKey: "nav.inventory", icon: IconGrid, permission: "rate.view" },
  { to: "/channels", labelKey: "nav.channels", icon: IconLink, permission: "channel.view" },
  { to: "/invoices", labelKey: "nav.invoices", icon: IconReceipt, permission: "invoice.issue" },
  { to: "/guests", labelKey: "nav.guests", icon: IconGuests, permission: "guest.view" },
  { to: "/pos", labelKey: "nav.pos", icon: IconPos, permission: "pos.view" },
  { to: "/housekeeping", labelKey: "nav.housekeeping", icon: IconBroom, permission: "housekeeping.view" },
  { to: "/reports", labelKey: "nav.reports", icon: IconChart, permission: "report.operational" },
  { to: "/settings", labelKey: "nav.settings", icon: IconSettings, permission: "admin.settings" },
];

export default function Layout() {
  const { t, locale } = useI18n();
  const { user, logout, can } = useAuth();

  const items = NAV.filter((n) => !n.permission || can(n.permission));
  const roleName =
    user?.roles?.[0] && (locale === "ar" ? user.roles[0].name_ar : user.roles[0].name_en);

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-ground">
      {/* الشريط الجانبي — أول عنصر، فبيظهر يمين في العربي وشمال في الإنجليزي */}
      <aside className="w-[240px] shrink-0 bg-sidebar text-sidebar-ink flex flex-col">
        <div className="px-5 pt-6 pb-5 flex items-center gap-3">
          <span className="w-9 h-9 rounded-[8px] bg-white/10 grid place-items-center shrink-0">
            <IconWaves size={20} className="text-sidebar-ink" />
          </span>
          <div className="min-w-0">
            <div className="text-[17px] font-bold leading-tight text-white">
              {t("app.name")}
            </div>
            <div className="text-[11.5px] opacity-65 truncate">{t("app.tagline")}</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-0.5">
          {items.map(({ to, labelKey, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-3 h-11 px-3 rounded-[6px] text-[14px] transition-colors",
                  isActive
                    ? "bg-sidebar-active text-white font-bold"
                    : "hover:bg-white/8 text-sidebar-ink",
                )
              }
            >
              <Icon size={19} />
              <span className="truncate">{t(labelKey)}</span>
            </NavLink>
          ))}
          {/* صفحة الحجز العامة — بتتفتح في تبويب جديد لأنها للزوار مش للموظفين */}
          <a
            href="/book"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 h-11 px-3 rounded-[6px] text-[14px] hover:bg-white/8 text-sidebar-ink mt-1 border-t border-white/10 pt-3"
          >
            <IconWaves size={19} />
            <span className="truncate">{t("nav.book")}</span>
          </a>
        </nav>

        <div className="px-3 pb-3 pt-2 border-t border-white/10">
          <div className="flex items-center gap-2 px-2 py-2">
            <span className="w-8 h-8 rounded-full bg-white/12 grid place-items-center text-[13px] font-bold shrink-0">
              {(locale === "ar" ? user?.full_name_ar : user?.full_name_en)?.[0] ?? "?"}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-bold truncate text-white">
                {locale === "ar" ? user?.full_name_ar : user?.full_name_en}
              </div>
              <div className="text-[11.5px] opacity-65 truncate">{roleName}</div>
            </div>
            <button
              onClick={logout}
              title={t("action.logout")}
              aria-label={t("action.logout")}
              className="w-8 h-8 grid place-items-center rounded-[6px] hover:bg-white/10 shrink-0"
            >
              <IconLogout size={17} />
            </button>
          </div>
        </div>
      </aside>

      {/* منطقة المحتوى */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}

/** أزرار اللغة والثيم — بتتحط في شريط كل شاشة. */
export function TopBarToggles() {
  const { toggle: toggleLocale } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  return (
    <div className="flex items-center gap-1 shrink-0">
      <button
        onClick={toggleLocale}
        className="w-9 h-9 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
        title="العربية / English"
        aria-label="Switch language"
      >
        <IconGlobe size={18} />
      </button>
      <button
        onClick={toggleTheme}
        className="w-9 h-9 grid place-items-center rounded-[6px] text-ink-2 hover:bg-surface-2"
        title={theme === "dark" ? "Light" : "Dark"}
        aria-label="Switch theme"
      >
        {theme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </button>
    </div>
  );
}
