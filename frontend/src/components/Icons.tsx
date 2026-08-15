/** أيقونات خطية رفيعة — بدون مكتبات، وبتاخد لون النص. */

type P = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IconDashboard = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <rect x="3" y="3" width="7" height="8" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="11" width="7" height="10" rx="1.5" />
  </svg>
);

export const IconCalendar = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
    <path d="M7 14h4M7 17.5h7" />
  </svg>
);

export const IconArrows = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M4 8h13l-3.5-3.5M20 16H7l3.5 3.5" />
  </svg>
);

export const IconGuests = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
    <path d="M16 5.5a3 3 0 0 1 0 5.6M18 19.8c0-2.4-.9-4.2-2.3-5.3" />
  </svg>
);

export const IconPos = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <rect x="2.5" y="6" width="19" height="12" rx="2" />
    <circle cx="12" cy="12" r="2.6" />
    <path d="M6 9.5v5M18 9.5v5" />
  </svg>
);

export const IconBroom = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M16.5 3.5 11 9" />
    <path d="M13.5 7.5 6 15l3 3 7.5-7.5z" />
    <path d="M6 15c-1.5 1.5-2 3.5-2 5.5 2 0 4-.5 5.5-2" />
  </svg>
);

/** شبكة الإتاحة — صفوف فئات × أعمدة أيام */
export const IconGrid = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 10h18M3 15h18M9 10v10M15 10v10" />
  </svg>
);

/** المخازن — كرتونة */
export const IconBox = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5Z" />
    <path d="M3 7.5 12 12l9-4.5M12 12v9" />
  </svg>
);

/** الحسابات — ميزان بكفّتين */
export const IconScale = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M12 3v18M7 21h10" />
    <path d="M4.5 7h15M8 7 5 14M5 14h6M5 14a3 3 0 0 0 6 0M16 7l3 7M19 14h-6M13 14a3 3 0 0 0 6 0" />
  </svg>
);

/** العاملون — مجموعة أفراد */
export const IconStaff = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="12" cy="7" r="3" />
    <path d="M6.5 20a5.5 5.5 0 0 1 11 0" />
    <path d="M5.5 11.5a2.4 2.4 0 1 0-2-3.8M3 18c0-1.7.7-3 1.9-3.8" />
    <path d="M18.5 11.5a2.4 2.4 0 1 1 2-3.8M21 18c0-1.7-.7-3-1.9-3.8" />
  </svg>
);

/** الصيانة — مفتاح إنجليزي */
export const IconWrench = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M15.2 3.6a5.2 5.2 0 0 0-6.1 6.7l-5.4 5.4a1.9 1.9 0 0 0 0 2.7l1.9 1.9a1.9 1.9 0 0 0 2.7 0l5.4-5.4a5.2 5.2 0 0 0 6.7-6.1l-3 3-2.6-.6-.6-2.6Z" />
  </svg>
);

/** الفاتورة الإلكترونية — إيصال مسنّن من تحت */
export const IconReceipt = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M5 3h14v16.5l-2.3-1.4-2.35 1.4-2.35-1.4-2.35 1.4L7.3 18.1 5 19.5Z" />
    <path d="M8.5 8h7M8.5 12h7" />
  </svg>
);

/** الربط بالقنوات — عقدة مركزية بتوزّع على أطراف */
export const IconLink = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="2.6" />
    <circle cx="4.5" cy="5" r="1.8" />
    <circle cx="19.5" cy="5" r="1.8" />
    <circle cx="4.5" cy="19" r="1.8" />
    <circle cx="19.5" cy="19" r="1.8" />
    <path d="m6 6.3 4 4M18 6.3l-4 4M6 17.7l4-4M18 17.7l-4-4" />
  </svg>
);

export const IconChart = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);

export const IconSettings = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M22 12h-3M5 12H2M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1M18.4 18.4l-2.1-2.1M7.7 7.7 5.6 5.6" />
  </svg>
);

export const IconSearch = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const IconChevronRight = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="m9 5 7 7-7 7" />
  </svg>
);

export const IconChevronLeft = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="m15 5-7 7 7 7" />
  </svg>
);

export const IconMoon = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </svg>
);

export const IconSun = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M22 12h-2M4 12H2M18.4 5.6l-1.4 1.4M7 17l-1.4 1.4M18.4 18.4 17 17M7 7 5.6 5.6" />
  </svg>
);

export const IconGlobe = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.5 2.6 2.5 15.4 0 18M12 3c-2.5 2.6-2.5 15.4 0 18" />
  </svg>
);

export const IconLock = ({ size = 14, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <rect x="4" y="10" width="16" height="11" rx="2" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);

export const IconPlus = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const IconMinus = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M5 12h14" />
  </svg>
);

export const IconTrash = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />
  </svg>
);

export const IconSend = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M21 3 10.5 13.5M21 3l-6.5 18-4-8-8-4z" />
  </svg>
);

export const IconLogout = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M14 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8" />
    <path d="M17 15l3-3-3-3M20 12H9" />
  </svg>
);

export const IconWarning = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M12 4 2.5 20h19z" />
    <path d="M12 10v4M12 17.2v.1" />
  </svg>
);

export const IconCheck = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="m4 12 5 5L20 6" />
  </svg>
);

export const IconX = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const IconArrowUp = ({ size = 14, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M12 19V5M6 11l6-6 6 6" />
  </svg>
);

export const IconArrowDown = ({ size = 14, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M12 5v14M6 13l6 6 6-6" />
  </svg>
);

export const IconWaves = ({ size = 22, className }: P) => (
  <svg {...base(size)} className={className} aria-hidden="true">
    <path d="M2 8c2.5-2 4.5-2 7 0s4.5 2 7 0 4.5-2 6 0" />
    <path d="M2 13c2.5-2 4.5-2 7 0s4.5 2 7 0 4.5-2 6 0" />
    <path d="M2 18c2.5-2 4.5-2 7 0s4.5 2 7 0 4.5-2 6 0" />
  </svg>
);
