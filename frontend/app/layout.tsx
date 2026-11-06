import type { Metadata } from "next";
import { Nunito_Sans } from "next/font/google";
import "./globals.css";

const font = Nunito_Sans({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "Traductor de libros PDF",
  description: "Traduce libros PDF del inglés al español conservando su diseño",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className={font.className}>{children}</body>
    </html>
  );
}
