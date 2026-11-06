"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { getJob, jobAction, type JobStatus, type StageState } from "@/lib/api";
import {
  Bulb, IconArrowLeft, IconCheck, IconDownload, IconHourglass, IconLayers, IconRefresh, IconWand, IconWarn, IconX,
  Planet, Robot, Sparkle,
} from "../../components/art";

const STATE_TEXT: Record<StageState, string> = {
  completed: "Completado",
  in_progress: "En progreso",
  pending: "Pendiente",
  error: "Error",
  cancelled: "Cancelado",
  paused: "En pausa",
};

const STAGE_MESSAGE: Record<string, string> = {
  analyze: "Estamos analizando las páginas del libro.",
  ocr: "Estamos buscando texto dentro de las imágenes.",
  protect: "Estamos identificando nombres, códigos y términos que no deben cambiar.",
  translate: "Estamos traduciendo el contenido.",
  rebuild: "Estamos colocando la traducción en cada página.",
  validate: "Estamos revisando que el libro traducido esté completo.",
};

function BadgeIcon({ state }: { state: StageState }) {
  if (state === "completed") return <IconCheck width={18} height={18} strokeWidth={3} />;
  if (state === "in_progress") return <IconHourglass width={18} height={18} />;
  if (state === "error" || state === "cancelled") return <IconX width={16} height={16} strokeWidth={3} />;
  return <span aria-hidden>•</span>;
}

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await getJob(id);
        if (!alive) return;
        setJob(j);
        setError(null);
        if (!["done", "failed", "cancelled"].includes(j.status)) timer = setTimeout(tick, 1500);
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message);
        timer = setTimeout(tick, 4000);
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, job?.status === "queued"]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(action: "cancel" | "resume") {
    try {
      setJob(await jobAction(id, action));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!job) {
    return (
      <main>
        <section className="card"><p style={{ margin: 0 }}>{error ?? "Cargando…"}</p></section>
      </main>
    );
  }

  const done = job.status === "done";
  const active = job.status === "queued" || job.status === "running";
  const stopped = job.status === "cancelled" || job.status === "failed";
  const message =
    job.status === "queued" ? "Tu libro está en la cola y comenzará en breve." :
    job.status === "cancelled" ? "El proceso fue cancelado. Puedes reanudarlo cuando quieras." :
    job.status === "failed" ? "El proceso se detuvo." :
    job.status === "paused" ? "El proceso está en pausa." :
    STAGE_MESSAGE[job.stage] ?? "Procesando…";

  return (
    <main>
      <Link href="/" className="back"><IconArrowLeft width={18} height={18} /> <u>Subir otro libro</u></Link>

      <section className="job-hero">
        <IconWand className="wand" width={52} height={52} strokeWidth={2.2} />
        <div>
          <h1>{done ? "¡Tu libro está listo!" : "Traduciendo tu libro"}</h1>
          <p>{job.original_name.replace(/\.pdf$/i, "")}{job.page_count ? ` · ${job.page_count} páginas` : ""}</p>
        </div>
        <Planet className="planet" />
        <Sparkle className="deco" size={18} color="#2e9b70" style={{ left: "62%", top: 0 }} />
        <Sparkle className="deco" size={14} color="#2e9b70" style={{ left: "70%", top: 40 }} />
      </section>

      {error && <div className="alert error" role="alert"><IconWarn /><span>{error}</span></div>}
      {job.error && <div className="alert error" role="alert"><IconWarn /><span>{job.error}</span></div>}

      {!done && (
        <section className="card progress-card" aria-live="polite">
          <Robot className="robot" />
          <div>
            <h2>{message}</h2>
            <div className={`progress ${active ? "" : "idle"}`} role="progressbar" aria-valuenow={job.progress}
              aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${Math.max(job.progress, active ? 3 : 0)}%` }} />
            </div>
            <p className="pct">
              {Math.round(job.progress)}%
              {job.current_page ? <small>página {job.current_page} de {job.page_count}</small> : null}
            </p>
            <div className="row" style={{ marginTop: 14 }}>
              {active && (
                <button className="btn secondary" onClick={() => act("cancel")}><IconX width={18} height={18} /> Cancelar</button>
              )}
              {stopped && (
                <button className="btn" onClick={() => act("resume")}><IconRefresh width={20} height={20} /> Reanudar</button>
              )}
            </div>
          </div>
        </section>
      )}

      {done && (
        <section className="card">
          <div className="result">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/jobs/${job.id}/pages/1/preview?version=translated&dpi=60`} alt="Portada del libro traducido" />
            <div>
              <h2>Resultado</h2>
              <p><strong>Archivo:</strong> {job.output_name}</p>
              <p><strong>Páginas:</strong> {job.page_count}</p>
              <p><strong>Páginas para revisar:</strong> {job.review_pages.length}</p>
              <div className="row">
                <a className="btn" href={`/api/jobs/${job.id}/download`}><IconDownload /> Descargar libro</a>
                <a className="btn secondary" href={`/api/jobs/${job.id}/report`}>Descargar reporte</a>
              </div>
            </div>
          </div>
          {job.review_pages.length > 0 && (
            <div className="alert warn">
              <IconWarn />
              <div>
                <strong>Páginas que conviene revisar:</strong>
                <ul>
                  {job.review_pages.slice(0, 20).map((p) => (
                    <li key={p.page}>Página {p.page}: {p.reasons.join("; ")}</li>
                  ))}
                </ul>
                {job.review_pages.length > 20 && <p>… y {job.review_pages.length - 20} más (ver reporte).</p>}
              </div>
            </div>
          )}
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <IconLayers className="head-icon" width={38} height={38} />
          <h2>Etapas</h2>
        </div>
        <ul className="stages">
          {job.stages.map((s) => (
            <li key={s.key} className={s.state}>
              <span className={`dot ${s.state}`} aria-hidden>
                {s.state === "completed" && <IconCheck width={16} height={16} strokeWidth={3.2} />}
                {(s.state === "error" || s.state === "cancelled") && <IconX width={14} height={14} strokeWidth={3} />}
              </span>
              <span className="name">{s.label}</span>
              <span className={`badge ${s.state}`}><BadgeIcon state={s.state} /> {STATE_TEXT[s.state]}</span>
            </li>
          ))}
        </ul>
      </section>

      {!done && (
        <div className="tip">
          <Bulb className="bulb" />
          <span>
            Este proceso puede tardar unos minutos.<br />
            Puedes cerrar esta ventana y volver más tarde a esta misma dirección: la traducción sigue en curso.
          </span>
          <Sparkle className="deco" size={26} style={{ right: 34, top: 18 }} />
        </div>
      )}
    </main>
  );
}
