import type { Metadata } from "next";
import { Inter, Inter_Tight } from "next/font/google";

import { AppFrame } from "@/components/layout/app-frame";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const interTight = Inter_Tight({
  variable: "--font-polysans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "FrontDesk · Clínica Arenal",
  description:
    "Panel de control del agente de IA para recepción de Clínica Arenal.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es"
      className={`${inter.variable} ${interTight.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background font-sans text-graphite">
        <AppFrame>{children}</AppFrame>
      </body>
    </html>
  );
}
