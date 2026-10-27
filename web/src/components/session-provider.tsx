"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import type { SetupStatus, User } from "@/lib/types";

interface SessionValue {
  user: User | null;
  status: SetupStatus | null;
  loading: boolean;
  isAdmin: boolean;
  isSteward: boolean;
  setUser: (user: User | null) => void;
  refreshStatus: () => Promise<SetupStatus | null>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refreshStatus();
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch (e) {
        if (!cancelled && e instanceof ApiError && e.status === 401) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      router.replace("/login");
    };
    window.addEventListener("converdata:unauthorized", onUnauthorized);
    return () => window.removeEventListener("converdata:unauthorized", onUnauthorized);
  }, [router]);

  useEffect(() => {
    if (loading) return;
    if (!user && pathname !== "/login") router.replace("/login");
  }, [loading, user, pathname, router]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {}
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({
      user,
      status,
      loading,
      isAdmin: !!user?.roles.includes("data_admin"),
      isSteward: !!user?.roles.includes("steward"),
      setUser,
      refreshStatus,
      logout,
    }),
    [user, status, loading, refreshStatus, logout],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession fuera de SessionProvider");
  return ctx;
}
