"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { getJob, jobAction, type JobStatus, type StageState } from "@/lib/api";

const STATE_TEXT: Record<StageState, string> = {
  completed: "✓ Completado",
  in_progress: "⏳ En progreso",
  pending: "• Pendiente",
  error: "✕ Error",
  cancelled: "✕ Cancelado",
  paused: "❚❚ En pausa",
};

const STAGE_MESSAGE: Record<string, string> = {
  analyze: "Estamos analizando las páginas del libro.",
  ocr: "Estamos buscando texto dentro de las imágenes.",
  protect: "Estamos identificando nombres, códigos y términos que no deben cambiar.",
  translate: "Estamos traduciendo el contenido.",
  rebuild: "Estamos colocando la traducción en cada página.",
  validate: "Estamos revisando que el libro traducido esté completo.",
};

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
        <p>{error ?? "Cargando…"}</p>
      </main>
    );
  }

  const done = job.status === "done";
  const active = job.status === "queued" || job.status === "running";

  return (
    <main>
      <Link href="/" className="muted">← Subir otro libro</Link>
      <h1 style={{ marginTop: 12 }}>{done ? "¡Tu libro está listo!" : "Traduciendo tu libro"}</h1>
      <p className="muted">{job.original_name} · {job.page_count} páginas</p>

      {error && <div className="alert error" role="alert">❌ {error}</div>}
      {job.error && <div className="alert error" role="alert">❌ {job.error}</div>}

      {!done && (
        <section className="card" aria-live="polite">
          <p style={{ margin: 0 }}>
            {job.status === "queued" ? "Tu libro está en la cola y comenzará en breve." :
              job.status === "cancelled" ? "El proceso fue cancelado. Puedes reanudarlo cuando quieras." :
              job.status === "failed" ? "El proceso se detuvo." : STAGE_MESSAGE[job.stage] ?? "Procesando…"}
          </p>
          <div className="progress" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${job.progress}%` }} />
          </div>
          <p className="muted" style={{ margin: 0 }}>
            {Math.round(job.progress)}%{job.current_page ? ` · página ${job.current_page} de ${job.page_count}` : ""}
          </p>
          <div className="row">
            {active && <button className="btn secondary" onClick={() => act("cancel")}>Cancelar</button>}
            {(job.status === "cancelled" || job.status === "failed") && (
              <button className="btn" onClick={() => act("resume")}>Reanudar</button>
            )}
          </div>
        </section>
      )}

      <section className="card">
        <h2>Etapas</h2>
        <ul className="stages">
          {job.stages.map((s) => (
            <li key={s.key}>
              <span>{s.label}</span>
              <span className={`badge ${s.state}`}>{STATE_TEXT[s.state]}</span>
            </li>
          ))}
        </ul>
      </section>

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
                <a className="btn" href={`/api/jobs/${job.id}/download`}>⬇ Descargar libro</a>
                <a className="btn secondary" href={`/api/jobs/${job.id}/report`}>Descargar reporte</a>
              </div>
            </div>
          </div>
          {job.review_pages.length > 0 && (
            <div className="alert warn">
              <strong>Páginas que conviene revisar:</strong>
              <ul>
                {job.review_pages.slice(0, 20).map((p) => (
                  <li key={p.page}>Página {p.page}: {p.reasons.join("; ")}</li>
                ))}
              </ul>
              {job.review_pages.length > 20 && <p>… y {job.review_pages.length - 20} más (ver reporte).</p>}
            </div>
          )}
        </section>
      )}
    </main>
  );
}
