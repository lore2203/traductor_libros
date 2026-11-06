"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getHealth, uploadBook } from "@/lib/api";
import {
  BooksHero, CloudUpload, FlagES, FlagUK, IconArrowRight, IconChevron, IconInfo, IconWand, IconWarn,
  LogoBook, OpenBook, Rays, Sparkle,
} from "./components/art";

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maxMb, setMaxMb] = useState(200);
  const [configured, setConfigured] = useState(true);

  useEffect(() => {
    getHealth()
      .then((h) => {
        setMaxMb(h.max_upload_mb);
        setConfigured(h.translation_configured);
      })
      .catch(() => setError("No pudimos conectar con el servidor. Verifica que esté en funcionamiento."));
  }, []);

  function pick(f: File | undefined | null) {
    setError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) return setError("Solo se admiten archivos PDF.");
    if (f.size > maxMb * 1024 * 1024) return setError(`El archivo supera el límite de ${maxMb} MB.`);
    setFile(f);
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const job = await uploadBook(file, rights);
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="hero">
        <div>
          <h1>
            Traductor
            <Rays className="rays" size={40} />
            <br />
            de Libros
          </h1>
          <p>Sube un libro en PDF en inglés y recibe su versión en español con el mismo diseño.</p>
        </div>
        <BooksHero className="hero-art" />
        <Sparkle className="deco" size={20} color="#2e9b70" style={{ left: "52%", top: 40 }} />
      </section>

      {!configured && (
        <div className="alert warn" role="status">
          <IconWarn />
          <span>El servicio de traducción aún no está configurado. El administrador debe agregar la llave de DeepSeek.</span>
        </div>
      )}

      <section className="card" aria-labelledby="upload-title">
        <div className="card-head">
          <span className="step" aria-hidden>1</span>
          <h2 id="upload-title">Elige tu libro</h2>
          <LogoBook size={38} className="head-icon" />
        </div>

        <div
          className={`dropzone ${drag ? "active" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="Zona para arrastrar y soltar el PDF o seleccionarlo"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            pick(e.dataTransfer.files?.[0]);
          }}
        >
          <span className="cloud">
            <CloudUpload size={100} />
            <Rays className="rays" size={34} />
          </span>
          {file ? (
            <p><span className="file-chip">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB</span></p>
          ) : (
            <p><strong>Arrastra el PDF aquí</strong> o <strong>haz clic para seleccionarlo</strong></p>
          )}
          <p className="muted">{file ? "Haz clic para elegir otro archivo" : `Tamaño máximo: ${maxMb} MB`}</p>
          <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>

        <div className="langs">
          <label className="lang">
            <FlagUK />
            <span style={{ flex: 1 }}>
              <small>Idioma de origen:</small>
              <select aria-label="Idioma de origen" defaultValue="en"><option value="en">Inglés</option></select>
            </span>
            <IconChevron className="chev" />
          </label>
          <label className="lang">
            <FlagES />
            <span style={{ flex: 1 }}>
              <small>Idioma de destino:</small>
              <select aria-label="Idioma de destino" defaultValue="es"><option value="es">Español</option></select>
            </span>
            <IconChevron className="chev" />
          </label>
        </div>

        <div className="note">
          <IconInfo width={24} height={24} />
          <span>
            Funciona mejor con PDF digitales (exportados desde un programa de diseño). Los PDF escaneados pueden
            requerir más revisión. No se admiten PDF protegidos con contraseña.
          </span>
        </div>

        <label className="field">
          <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
          <span>Confirmo que tengo derechos para traducir y usar este libro.</span>
        </label>

        {error && (
          <div className="alert error" role="alert"><IconWarn /><span>{error}</span></div>
        )}

        <div className="row">
          <span className="cta">
            <button className="btn" disabled={!file || !rights || busy} onClick={submit}>
              <IconWand /> {busy ? "Subiendo…" : "Traducir libro"} {!busy && <IconArrowRight />}
            </button>
            <Rays className="rays" size={30} />
          </span>
        </div>

        <OpenBook className="deco" style={{ right: 30, bottom: 18, width: 120 }} />
        <Sparkle className="deco" size={18} style={{ right: 170, bottom: 70 }} />
      </section>
    </main>
  );
}
