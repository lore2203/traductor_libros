import type { Metadata } from "next";
import Link from "next/link";
import { Nunito } from "next/font/google";
import { IconHome, LogoBook } from "./components/art";
import "./globals.css";

const font = Nunito({ subsets: ["latin"], weight: ["400", "600", "700", "800", "900"], display: "swap" });

export const metadata: Metadata = {
  title: "AstroBooks · Traductor de libros",
  description: "Traduce libros PDF del inglés al español conservando su diseño",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className={font.className}>
        <div className="shell">
          <header className="topbar">
            <Link href="/" className="brand" aria-label="AstroBooks, inicio">
              <LogoBook size={36} />
              <span>AstroBooks</span>
            </Link>
            <nav className="topnav">
              <Link href="/" className="pill"><IconHome width={20} height={20} /> Inicio</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
