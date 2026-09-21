import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Servicing Desk",
  description: "Borrower correspondence queue — Reg X §1024.35/.36",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-stone-50 text-stone-900">
        <header className="border-b border-stone-200 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-3 flex items-baseline gap-6">
            <Link href="/" className="font-semibold tracking-tight">
              Servicing Desk
            </Link>
            <Link href="/intake" className="text-sm text-stone-600 hover:underline">
              Intake
            </Link>
            <span className="text-xs text-stone-500">
              Notice of Error · Request for Information · Payoff — Reg X §1024.35/.36, Reg Z §1026.36(c)(3)
            </span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-6 flex-1">{children}</main>
      </body>
    </html>
  );
}
