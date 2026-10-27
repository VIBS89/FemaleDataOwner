"use client";

import { Loader2 } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { ConversationsProvider } from "@/components/chat/conversations";
import { useSession } from "@/components/session-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();

  if (loading || !user) {
    return (
      <div className="text-muted-foreground flex min-h-svh items-center justify-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin" /> Cargando…
      </div>
    );
  }

  return (
    <ConversationsProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="min-w-0">{children}</SidebarInset>
      </SidebarProvider>
    </ConversationsProvider>
  );
}
