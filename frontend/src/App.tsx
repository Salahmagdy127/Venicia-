import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import { Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";

// كل شاشة بتتحمّل لوحدها — أول فتح للنظام بيبقى أسرع
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const TapeChart = lazy(() => import("@/pages/TapeChart"));
const FrontDesk = lazy(() => import("@/pages/FrontDesk"));
const Inventory = lazy(() => import("@/pages/Inventory"));
const Channels = lazy(() => import("@/pages/Channels"));
const Invoices = lazy(() => import("@/pages/Invoices"));
const Maintenance = lazy(() => import("@/pages/Maintenance"));
// صفحة الحجز العامة — بره الشريط الجانبي وبره تسجيل الدخول
const Book = lazy(() => import("@/pages/Book"));
const Menu = lazy(() => import("@/pages/Menu"));
const Guests = lazy(() => import("@/pages/Guests"));
const Pos = lazy(() => import("@/pages/Pos"));
const Housekeeping = lazy(() => import("@/pages/Housekeeping"));
const Reports = lazy(() => import("@/pages/Reports"));
const Settings = lazy(() => import("@/pages/Settings"));

function FullScreenLoading() {
  return (
    <div className="h-screen w-screen grid place-items-center bg-ground">
      <Loading />
    </div>
  );
}

/** يمنع الدخول لأي شاشة قبل تسجيل الدخول، ويرجّع المستخدم لمكانه بعد الدخول. */
function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullScreenLoading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <FullScreenLoading />;
  if (user) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <Login />
          </PublicOnly>
        }
      />

      {/* الصفحات العامة — مش وراها تسجيل دخول */}
      <Route
        path="/book"
        element={
          <Suspense fallback={<FullScreenLoading />}>
            <Book />
          </Suspense>
        }
      />
      <Route
        path="/menu/:code"
        element={
          <Suspense fallback={<FullScreenLoading />}>
            <Menu />
          </Suspense>
        }
      />

      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route
          path="/"
          element={
            <Suspense fallback={<Loading />}>
              <Dashboard />
            </Suspense>
          }
        />
        <Route
          path="/tape-chart"
          element={
            <Suspense fallback={<Loading />}>
              <TapeChart />
            </Suspense>
          }
        />
        <Route
          path="/front-desk"
          element={
            <Suspense fallback={<Loading />}>
              <FrontDesk />
            </Suspense>
          }
        />
        <Route
          path="/inventory"
          element={
            <Suspense fallback={<Loading />}>
              <Inventory />
            </Suspense>
          }
        />
        <Route
          path="/channels"
          element={
            <Suspense fallback={<Loading />}>
              <Channels />
            </Suspense>
          }
        />
        <Route
          path="/maintenance"
          element={
            <Suspense fallback={<Loading />}>
              <Maintenance />
            </Suspense>
          }
        />
        <Route
          path="/invoices"
          element={
            <Suspense fallback={<Loading />}>
              <Invoices />
            </Suspense>
          }
        />
        <Route
          path="/guests"
          element={
            <Suspense fallback={<Loading />}>
              <Guests />
            </Suspense>
          }
        />
        <Route
          path="/pos"
          element={
            <Suspense fallback={<Loading />}>
              <Pos />
            </Suspense>
          }
        />
        <Route
          path="/housekeeping"
          element={
            <Suspense fallback={<Loading />}>
              <Housekeeping />
            </Suspense>
          }
        />
        <Route
          path="/reports"
          element={
            <Suspense fallback={<Loading />}>
              <Reports />
            </Suspense>
          }
        />
        <Route
          path="/settings"
          element={
            <Suspense fallback={<Loading />}>
              <Settings />
            </Suspense>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
