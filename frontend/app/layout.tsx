import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import Link from "next/link";
import { HeaderNav } from "@/components/HeaderNav";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Mulp · Claims Intelligence",
  description: "AI-powered health-insurance claims adjudication with full explainability.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${fraunces.variable} ${inter.variable}`}>
      <body className="min-h-dvh">
        <header className="sticky top-0 z-30 border-b border-border bg-bg/80 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
            <Link href="/" className="pressable flex items-center gap-2.5">
              <span className="grid size-7 place-items-center rounded-md bg-brand font-display text-lg leading-none text-cream">
                p
              </span>
              <span className="text-[15px] font-medium tracking-tight text-ink">
                Mulp <span className="text-ink-faint">·</span>{" "}
                <span className="text-ink-muted">Claims Intelligence</span>
              </span>
            </Link>
            <HeaderNav />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 py-10 text-xs text-ink-faint">
          Decisions are policy-driven. Every outcome is fully traceable.
        </footer>
      </body>
    </html>
  );
}
