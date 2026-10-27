"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  ChevronsUpDown,
  Database,
  Inbox,
  LogOut,
  MessageSquare,
  MessageSquarePlus,
  PenLine,
  Server,
  Settings2,
  Trash2,
} from "lucide-react";

import { BrandMark } from "@/components/brand";
import { useConversations } from "@/components/chat/conversations";
import { useSession } from "@/components/session-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { relativeTime } from "@/lib/format";

export function AppSidebar() {
  const { user, isAdmin, isSteward, logout } = useSession();
  const { conversations, activeId, select, remove } = useConversations();
  const { setOpenMobile } = useSidebar();
  const pathname = usePathname();
  const router = useRouter();

  const nav = [
    { href: "/", label: "Preguntar", icon: MessageSquare },
    { href: "/catalogo", label: "Catálogo", icon: Database },
    { href: "/solicitudes", label: "Mis solicitudes", icon: Inbox },
    ...(isSteward ? [{ href: "/curacion", label: "Curación", icon: PenLine }] : []),
    ...(isAdmin ? [{ href: "/metricas", label: "Métricas", icon: BarChart3 }] : []),
    ...(isAdmin ? [{ href: "/admin", label: "Administración", icon: Settings2 }] : []),
  ];

  const newChat = () => {
    select(null);
    setOpenMobile(false);
    router.push("/");
  };

  const initials = (user?.user_id ?? "?").replace(/^.*\\/, "").slice(0, 2).toUpperCase();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild className="hover:bg-transparent">
              <Link href="/" onClick={newChat}>
                <BrandMark />
                <div className="grid flex-1 text-left leading-tight">
                  <span className="font-semibold tracking-tight">ConverData</span>
                  <span className="text-muted-foreground text-xs">Descubrimiento de datos</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <Button onClick={newChat} className="mt-1 w-full justify-start gap-2 group-data-[collapsible=icon]:hidden">
          <MessageSquarePlus /> Nueva pregunta
        </Button>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {nav.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    tooltip={item.label}
                    isActive={item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)}
                  >
                    <Link href={item.href} onClick={() => setOpenMobile(false)}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel>Conversaciones recientes</SidebarGroupLabel>
          <SidebarGroupContent>
            {conversations.length === 0 ? (
              <p className="text-muted-foreground px-2 py-1.5 text-xs">Tus preguntas aparecerán aquí.</p>
            ) : (
              <SidebarMenu>
                {conversations.map((c) => (
                  <SidebarMenuItem key={c.id}>
                    <SidebarMenuButton
                      isActive={pathname === "/" && c.id === activeId}
                      onClick={() => {
                        select(c.id);
                        setOpenMobile(false);
                        if (pathname !== "/") router.push("/");
                      }}
                      className="h-auto py-1.5"
                    >
                      <div className="grid min-w-0 flex-1">
                        <span className="truncate">{c.title}</span>
                        <span className="text-muted-foreground text-[11px]">{relativeTime(c.updatedAt)}</span>
                      </div>
                    </SidebarMenuButton>
                    <SidebarMenuAction showOnHover onClick={() => remove(c.id)} aria-label="Eliminar conversación">
                      <Trash2 />
                    </SidebarMenuAction>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent">
                  <Avatar className="size-8 rounded-lg">
                    <AvatarFallback className="bg-accent text-accent-foreground rounded-lg text-xs font-medium">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight">
                    <span className="truncate font-medium">{user?.user_id}</span>
                    <span className="text-muted-foreground truncate text-xs">
                      {isAdmin ? "Administrador de datos" : isSteward ? "Responsable de datos" : "Consulta"}
                    </span>
                  </div>
                  <ChevronsUpDown className="ml-auto size-4" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-64">
                <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Conectado a</DropdownMenuLabel>
                {user?.servers.map((s) => (
                  <DropdownMenuItem key={s.id} disabled className="opacity-100">
                    <Server /> {s.alias}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout}>
                  <LogOut /> Cerrar sesión
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
