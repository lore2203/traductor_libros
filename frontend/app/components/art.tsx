/* Ilustraciones e íconos en SVG (sin dependencias ni imágenes externas). */
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const G = "#1d7a56";
const G2 = "#2e9b70";
const GD = "#14573e";
const CREAM = "#fbf6e9";
const Y = "#f6c445";

const icon = (p: P) => ({
  width: 22, height: 22, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, ...p,
});

export const IconHome = (p: P) => (
  <svg {...icon(p)}><path d="M3 11 12 4l9 7" /><path d="M5 10v10h5v-6h4v6h5V10" /></svg>
);
export const IconChevron = (p: P) => <svg {...icon(p)}><path d="m6 9 6 6 6-6" /></svg>;
export const IconArrowLeft = (p: P) => <svg {...icon(p)}><path d="M19 12H5M11 6l-6 6 6 6" /></svg>;
export const IconArrowRight = (p: P) => <svg {...icon(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
export const IconX = (p: P) => <svg {...icon(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>;
export const IconCheck = (p: P) => <svg {...icon(p)}><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>;
export const IconDownload = (p: P) => <svg {...icon(p)}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>;
export const IconRefresh = (p: P) => <svg {...icon(p)}><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" /></svg>;
export const IconInfo = (p: P) => (
  <svg {...icon({ ...p, stroke: "none" })}>
    <circle cx="12" cy="12" r="11" fill={G} />
    <rect x="10.8" y="10" width="2.4" height="7.5" rx="1.2" fill="#fff" />
    <circle cx="12" cy="6.9" r="1.5" fill="#fff" />
  </svg>
);
export const IconLayers = (p: P) => (
  <svg {...icon(p)}><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12.5 9 5 9-5" /><path d="m3 17 9 5 9-5" /></svg>
);
export const IconWand = (p: P) => (
  <svg {...icon(p)}>
    <path d="M4 20 15 9" /><path d="m13.5 7.5 3 3" />
    <path d="M18 2.5v3M16.5 4h3M20.5 9v2M19.5 10h2M9 2.5v2M8 3.5h2" />
  </svg>
);
export const IconWarn = (p: P) => (
  <svg {...icon(p)}><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17h.01" /></svg>
);
export const IconHourglass = (p: P) => (
  <svg {...icon({ ...p, stroke: "none" })}>
    <path d="M6 3h12v3.2c0 2-1.6 3.8-3.6 5.8 2 2 3.6 3.8 3.6 5.8V21H6v-3.2c0-2 1.6-3.8 3.6-5.8C7.6 10 6 8.2 6 6.2V3Z" fill="#e9a825" />
    <path d="M8.5 19h7c0-1.6-1.6-3-3.5-4.6C10.1 16 8.5 17.4 8.5 19Z" fill="#fff5d6" />
    <rect x="4.5" y="2" width="15" height="2.2" rx="1.1" fill="#9a6a12" />
    <rect x="4.5" y="19.8" width="15" height="2.2" rx="1.1" fill="#9a6a12" />
  </svg>
);

export function Sparkle({ size = 18, color = Y, ...p }: P & { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden {...p}>
      <path d="M12 0c.8 6.4 5.6 11.2 12 12-6.4.8-11.2 5.6-12 12-.8-6.4-5.6-11.2-12-12C6.4 11.2 11.2 6.4 12 0Z" fill={color} />
    </svg>
  );
}

/** Rayitas decorativas tipo «brillo» (como junto al título). */
export function Rays({ size = 34, ...p }: P & { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden {...p}>
      <g stroke={Y} strokeWidth="4.5" strokeLinecap="round">
        <path d="M8 22 14 6" /><path d="M16 26 30 14" /><path d="M20 34h14" />
      </g>
    </svg>
  );
}

export function LogoBook({ size = 34, ...p }: P & { size?: number }) {
  return (
    <svg width={size} height={size * 0.82} viewBox="0 0 44 36" aria-hidden {...p}>
      <path d="M22 7C17 3 9 2.5 3 4v27c6-1.5 14-1 19 3 5-4 13-4.5 19-3V4c-6-1.5-14-1-19 3Z" fill={G} />
      <path d="M22 9.5c-4-3-10-3.6-15-2.6v21.2c5-.8 11-.2 15 2.6Zm0 0c4-3 10-3.6 15-2.6v21.2c-5-.8-11-.2-15 2.6Z" fill="#e7f5ec" />
      <path d="M22 9.5v21.2" stroke={G} strokeWidth="1.6" />
      <g stroke={G2} strokeWidth="1.5" strokeLinecap="round">
        <path d="M10 13c2.5-.4 5-.2 8 .8M10 18c2.5-.4 5-.2 8 .8M26 13.8c3-1 5.5-1.2 8-.8M26 18.8c3-1 5.5-1.2 8-.8" />
      </g>
    </svg>
  );
}

export function CloudUpload({ size = 96, ...p }: P & { size?: number }) {
  return (
    <svg width={size} height={size * 0.75} viewBox="0 0 96 72" aria-hidden {...p}>
      <path d="M28 58H22a17 17 0 0 1-2-33.9A22 22 0 0 1 62 18a16 16 0 0 1 14 36.5c-1.6 1.3-4 3.5-8 3.5h-4"
        fill="none" stroke={G} strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M48 66V36M37 46l11-11 11 11" fill="none" stroke={G} strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FlagUK({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" aria-hidden>
      <defs><clipPath id="fuk"><circle cx="15" cy="15" r="15" /></clipPath></defs>
      <g clipPath="url(#fuk)">
        <rect width="30" height="30" fill="#24418f" />
        <path d="M0 0 30 30M30 0 0 30" stroke="#fff" strokeWidth="6" />
        <path d="M0 0 30 30M30 0 0 30" stroke="#d6283a" strokeWidth="2.2" />
        <path d="M15 0v30M0 15h30" stroke="#fff" strokeWidth="9" />
        <path d="M15 0v30M0 15h30" stroke="#d6283a" strokeWidth="5" />
      </g>
    </svg>
  );
}

export function FlagES({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" aria-hidden>
      <defs><clipPath id="fes"><circle cx="15" cy="15" r="15" /></clipPath></defs>
      <g clipPath="url(#fes)">
        <rect width="30" height="30" fill="#c8102e" />
        <rect y="7.5" width="30" height="15" fill="#f8c300" />
        <rect x="7" y="11.5" width="4.5" height="6" rx="1" fill="#c8102e" opacity=".8" />
      </g>
    </svg>
  );
}

function Book({ x, y, w, h, cover, rot = 0 }: { x: number; y: number; w: number; h: number; cover: string; rot?: number }) {
  const cx = x + w / 2;
  const cy = y + h / 2;
  return (
    <g transform={`rotate(${rot} ${cx} ${cy})`}>
      <rect x={x} y={y + 4} width={w} height={h} rx="9" fill={GD} opacity=".25" />
      <rect x={x} y={y} width={w} height={h} rx="9" fill={cover} />
      <rect x={x + 26} y={y + 7} width={w - 30} height={h - 14} rx="4" fill={CREAM} />
      <g stroke="#e5dcc3" strokeWidth="1.4">
        {[0.3, 0.5, 0.7].map((f) => (
          <path key={f} d={`M${x + 30} ${y + 7 + (h - 14) * f}H${x + w - 6}`} />
        ))}
      </g>
      <rect x={x + 8} y={y + 6} width="4" height={h - 12} rx="2" fill={Y} />
      <rect x={x + 15} y={y + 6} width="4" height={h - 12} rx="2" fill={Y} opacity=".85" />
    </g>
  );
}

export function BooksHero(p: P) {
  return (
    <svg viewBox="0 0 320 250" role="img" aria-label="Pila de libros con una estrella" {...p}>
      <ellipse cx="170" cy="120" rx="140" ry="62" fill="none" stroke={G2} strokeWidth="2.5" opacity=".55"
        transform="rotate(-14 170 120)" strokeDasharray="300 18" />
      <ellipse cx="165" cy="232" rx="125" ry="12" fill={GD} opacity=".12" />
      <Book x={50} y={176} w={230} h={48} cover={GD} rot={-2} />
      <Book x={72} y={128} w={200} h={46} cover={G} rot={5} />
      <Book x={60} y={84} w={190} h={44} cover={G2} rot={-6} />
      <path d="M170 18l9.4 19 21 3-15.2 14.8 3.6 20.9L170 65.8 151.2 75.7l3.6-20.9L139.6 40l21-3Z" fill={Y}
        stroke="#e2a722" strokeWidth="2" strokeLinejoin="round" />
      <Sparkle x={36} y={56} size={18} color={G2} />
      <Sparkle x={290} y={150} size={14} color="#ffffff" />
      <Sparkle x={262} y={30} size={12} color={G2} />
      <Sparkle x={20} y={160} size={16} color={Y} />
    </svg>
  );
}

export function OpenBook(p: P) {
  return (
    <svg viewBox="0 0 140 80" aria-hidden {...p}>
      <ellipse cx="70" cy="72" rx="60" ry="6" fill={GD} opacity=".12" />
      <path d="M70 20C55 10 30 8 10 14l-4 50c20-6 46-4 64 6 18-10 44-12 64-6l-4-50c-20-6-45-4-60 6Z" fill={G} />
      <path d="M70 18C56 8 34 6 16 10l-3 48c18-4 41-2 57 8Zm0 0c14-10 36-12 54-8l3 48c-18-4-41-2-57 8Z" fill={CREAM} stroke="#e5dcc3" />
      <g stroke="#cfc4a6" strokeWidth="1.4" strokeLinecap="round">
        <path d="M24 22c12-2 26-1 38 4M22 32c12-2 27-1 40 4M21 42c12-2 27-1 40 4M78 26c12-5 26-6 38-4M78 36c13-5 27-6 40-4M79 46c13-5 27-6 40-4" />
      </g>
    </svg>
  );
}

export function Robot(p: P) {
  return (
    <svg viewBox="0 0 180 190" role="img" aria-label="Robot leyendo un libro" {...p}>
      <ellipse cx="92" cy="180" rx="70" ry="8" fill={GD} opacity=".12" />
      <g stroke={Y} strokeWidth="5" strokeLinecap="round"><path d="M14 30 24 44M8 56h14M30 14l4 14" /></g>
      {/* antena */}
      <path d="M92 18v14" stroke="#c9d6d0" strokeWidth="4" />
      <circle cx="92" cy="15" r="6" fill={G} />
      {/* cuerpo */}
      <path d="M50 120c0-20 18-32 42-32s42 12 42 32v40c0 10-8 16-18 16H68c-10 0-18-6-18-16Z" fill="#f4f8f6" stroke="#d6e2dc" strokeWidth="2" />
      <ellipse cx="44" cy="150" rx="12" ry="18" fill={G} />
      {/* cabeza */}
      <rect x="40" y="30" width="104" height="74" rx="34" fill="#f4f8f6" stroke="#d6e2dc" strokeWidth="2" />
      <rect x="28" y="52" width="16" height="30" rx="8" fill={G} />
      <rect x="140" y="52" width="16" height="30" rx="8" fill={G} />
      <rect x="54" y="42" width="76" height="50" rx="24" fill="#16302a" />
      <path d="M70 66c2-6 10-6 12 0M102 66c2-6 10-6 12 0" stroke="#7ef0c6" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <path d="M84 76c5 5 11 5 16 0" stroke="#7ef0c6" strokeWidth="3.5" strokeLinecap="round" fill="none" />
      {/* libro */}
      <path d="M78 130c14-8 32-8 46-2l6 40c-14-6-32-6-46 2Z" fill={G} />
      <path d="M124 128c14-6 26-6 38 0l-4 40c-12-6-24-6-28 0Z" fill={G2} />
      <path d="M84 132c12-6 26-6 38-1l5 32c-12-5-26-5-38 1Z" fill={CREAM} />
      <circle cx="80" cy="152" r="11" fill="#eef4f1" stroke="#d6e2dc" strokeWidth="2" />
      <circle cx="158" cy="146" r="10" fill="#eef4f1" stroke="#d6e2dc" strokeWidth="2" />
    </svg>
  );
}

export function Planet(p: P) {
  return (
    <svg viewBox="0 0 150 120" aria-hidden {...p}>
      <defs><clipPath id="pl"><circle cx="78" cy="62" r="40" /></clipPath></defs>
      <path d="M10 62A68 17 0 0 1 146 62" transform="rotate(-24 78 62)" fill="none" stroke={G} strokeWidth="5" />
      <circle cx="78" cy="62" r="40" fill={G2} />
      <g clipPath="url(#pl)">
        <circle cx="96" cy="44" r="40" fill="#4fb889" opacity=".55" />
        <circle cx="60" cy="40" r="6" fill="#4fb889" /><circle cx="98" cy="84" r="8" fill={G} opacity=".5" />
      </g>
      <circle cx="66" cy="62" r="3.5" fill={GD} /><circle cx="90" cy="62" r="3.5" fill={GD} />
      <path d="M70 72c5 4 11 4 16 0" stroke={GD} strokeWidth="3" fill="none" strokeLinecap="round" />
      <path d="M10 62A68 17 0 0 0 146 62" transform="rotate(-24 78 62)" fill="none" stroke={Y} strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function Bulb(p: P) {
  return (
    <svg viewBox="0 0 40 48" aria-hidden {...p}>
      <path d="M20 3a15 15 0 0 0-9 27c2 1.6 3 3.6 3 6h12c0-2.4 1-4.4 3-6A15 15 0 0 0 20 3Z" fill={Y} />
      <path d="M14 22c2-3 4 3 6 0s4 3 6 0" stroke="#d99b1e" strokeWidth="2" fill="none" strokeLinecap="round" />
      <rect x="13" y="37" width="14" height="4" rx="2" fill="#7d8e88" />
      <rect x="15" y="42" width="10" height="4" rx="2" fill="#7d8e88" />
    </svg>
  );
}
