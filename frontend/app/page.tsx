"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getHealth, uploadBook } from "@/lib/api";

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
      <h1>Traductor de libros</h1>
      <p className="muted">Sube un libro en PDF en inglés y recibe su versión en español con el mismo diseño.</p>

      {!configured && (
        <div className="alert warn" role="status">
          ⚠️ El servicio de traducción aún no está configurado. El administrador debe agregar la llave de DeepSeek.
        </div>
      )}

      <section className="card" aria-labelledby="upload-title">
        <h2 id="upload-title">1. Elige tu libro</h2>
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
          <p style={{ fontSize: 40, margin: 0 }} aria-hidden>📄</p>
          {file ? (
            <p><strong>{file.name}</strong> · {(file.size / 1024 / 1024).toFixed(1)} MB</p>
          ) : (
            <p><strong>Arrastra el PDF aquí</strong> o haz clic para seleccionarlo</p>
          )}
          <p className="muted">Tamaño máximo: {maxMb} MB</p>
          <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>

        <div className="langs">
          <div className="lang">Idioma de origen: <strong>Inglés</strong></div>
          <div className="lang">Idioma de destino: <strong>Español</strong></div>
        </div>

        <p className="muted" style={{ marginTop: 18 }}>
          Funciona mejor con PDF digitales (exportados desde un programa de diseño). Los PDF escaneados pueden
          requerir más revisión. No se admiten PDF protegidos con contraseña.
        </p>

        <label className="field">
          <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
          <span>Confirmo que tengo derechos para traducir y usar este libro.</span>
        </label>

        {error && <div className="alert error" role="alert">❌ {error}</div>}

        <div className="row">
          <button className="btn" disabled={!file || !rights || busy} onClick={submit}>
            {busy ? "Subiendo…" : "Traducir libro →"}
          </button>
        </div>
      </section>
    </main>
  );
}
