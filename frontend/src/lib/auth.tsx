import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, get, setToken, getToken } from "./api";

export type Role = {
  code: string;
  name_ar: string;
  name_en: string;
  max_discount_percent: number;
};

export type User = {
  id: number;
  username: string;
  full_name_ar: string;
  full_name_en: string;
  email: string | null;
  preferred_locale: string;
  is_superuser: boolean;
  property_id: number | null;
  roles: Role[];
  permissions: string[];
};

type Ctx = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  /** فحص صلاحية — بيدعم النجمة على مستوى الموديول */
  can: (permission: string) => boolean;
  maxDiscount: number;
};

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    get<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      form: { username, password },
    });
    setToken(res.access_token);
    setUser(await get<User>("/auth/me"));
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    location.href = "/login";
  }, []);

  const can = useCallback(
    (permission: string) => {
      if (!user) return false;
      if (user.is_superuser || user.permissions.includes("*")) return true;
      if (user.permissions.includes(permission)) return true;
      const module = permission.split(".")[0];
      return user.permissions.includes(`${module}.*`);
    },
    [user],
  );

  const maxDiscount = useMemo(() => {
    if (!user) return 0;
    if (user.is_superuser) return 100;
    return user.roles.reduce((max, r) => Math.max(max, r.max_discount_percent), 0);
  }, [user]);

  const value = useMemo<Ctx>(
    () => ({ user, loading, login, logout, can, maxDiscount }),
    [user, loading, login, logout, can, maxDiscount],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
