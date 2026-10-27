import type { Metadata } from "next";
import { SessionProvider } from "@/components/session-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: "ConverData · Descubrimiento de datos",
  description: "Asistente de IA que responde dónde está un dato, qué significa y cuánta confianza merece.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body className="antialiased">
        <SessionProvider>
          <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
        </SessionProvider>
        <Toaster position="top-center" richColors closeButton />
      </body>
    </html>
  );
}
