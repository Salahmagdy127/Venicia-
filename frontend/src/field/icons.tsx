/** أيقونات التطبيق الميداني — خط واحد، بتورث اللون من النص. */

type P = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export const Check = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

export const Camera = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7l1.3-2h7l1.3 2h1.7A2.5 2.5 0 0 1 21 8.5v9A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z" />
    <circle cx="12" cy="13" r="3.4" />
  </svg>
);

export const Moon = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 13.4A8.2 8.2 0 0 1 10.6 4a8.4 8.4 0 1 0 9.4 9.4" />
  </svg>
);

export const Lock = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <rect x="4" y="10.5" width="16" height="10" rx="2.2" />
    <path d="M8 10.5V7.6a4 4 0 0 1 8 0v2.9" />
  </svg>
);

export const Wrench = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M14.6 6.4a4.2 4.2 0 0 0 5.5 5.5l-8 8a2.5 2.5 0 0 1-3.6-3.5z" />
    <path d="M14.6 6.4 17.4 3.6" />
  </svg>
);

export const Broom = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M14 4 8.5 9.5" />
    <path d="M11.4 8.6 4 16v4h5l7.4-7.4z" />
    <path d="M9 20v-4h5" />
  </svg>
);

export const Clock = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M12 7.4V12l3 1.8" />
  </svg>
);

export const Cloud = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M6.5 18.5a3.9 3.9 0 0 1-.4-7.8 5.4 5.4 0 0 1 10.4-1.3 3.9 3.9 0 0 1 .5 7.6z" />
  </svg>
);

export const CloudOff = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M17.5 17.6H6.5a3.9 3.9 0 0 1-.4-7.8" />
    <path d="M8.6 6.7a5.4 5.4 0 0 1 8 3.3" />
    <path d="M3.5 3.5 20.5 20.5" />
  </svg>
);

export const Sync = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 12a8 8 0 0 1-13.7 5.6" />
    <path d="M4 12a8 8 0 0 1 13.7-5.6" />
    <path d="M17.7 3v3.4h-3.4M6.3 21v-3.4h3.4" />
  </svg>
);

export const Alert = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 4.5 21 19.5H3z" />
    <path d="M12 10v4M12 17.2v.1" />
  </svg>
);

export const List = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M9 6.5h11M9 12h11M9 17.5h11M4.2 6.5v.1M4.2 12v.1M4.2 17.5v.1" />
  </svg>
);

export const Plus = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 5.5v13M5.5 12h13" />
  </svg>
);

export const X = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const User = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="8.4" r="3.8" />
    <path d="M4.6 20a7.4 7.4 0 0 1 14.8 0" />
  </svg>
);

export const Cup = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M5 8h11v6.5a4.5 4.5 0 0 1-9 0z" />
    <path d="M16 9.5h1.8a2.2 2.2 0 0 1 0 4.4H16" />
    <path d="M4.5 20.5h12" />
  </svg>
);

/** علامة التطبيق — بحيرة وقمر، بتتحرك أول ما التطبيق يفتح. */
export const Mark = ({ size = 64, className }: P) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 64 64"
    fill="none"
    className={className}
    aria-hidden
  >
    <circle cx="32" cy="32" r="30" stroke="currentColor" strokeWidth="1.4" opacity="0.22" />
    <circle cx="41" cy="23" r="7.5" fill="currentColor" opacity="0.9" />
    <path
      d="M12 40c4-3.4 8-3.4 12 0s8 3.4 12 0 8-3.4 12 0"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      opacity="0.75"
    />
    <path
      d="M12 48c4-3.4 8-3.4 12 0s8 3.4 12 0 8-3.4 12 0"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      opacity="0.4"
    />
  </svg>
);
