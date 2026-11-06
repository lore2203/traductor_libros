export type StageState = "completed" | "in_progress" | "pending" | "error" | "cancelled" | "paused";

export interface JobStatus {
  id: number;
  status: "queued" | "running" | "paused" | "cancelled" | "done" | "failed";
  stage: string;
  progress: number;
  current_page: number | null;
  page_count: number;
  original_name: string;
  title_es: string | null;
  output_name: string | null;
  error: string | null;
  stages: { key: string; label: string; state: StageState }[];
  review_pages: { page: number; reasons: string[] }[];
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg =
      res.status === 413
        ? "El archivo es demasiado grande para el límite configurado."
        : res.status >= 500
          ? "El servidor no pudo procesar la solicitud. Verifica que el servicio esté en funcionamiento e inténtalo de nuevo."
          : "No pudimos completar la acción. Intenta de nuevo.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* respuesta sin JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function uploadBook(file: File, rightsConfirmed: boolean): Promise<JobStatus> {
  const form = new FormData();
  form.append("file", file);
  form.append("rights_confirmed", String(rightsConfirmed));
  form.append("source_lang", "en");
  form.append("target_lang", "es");
  let res: Response;
  try {
    res = await fetch("/api/jobs", { method: "POST", body: form });
  } catch {
    throw new Error("Se perdió la conexión mientras se subía el libro. Revisa que el servicio esté activo e inténtalo de nuevo.");
  }
  return parse(res);
}

export async function getJob(id: string | number): Promise<JobStatus> {
  return parse(await fetch(`/api/jobs/${id}`, { cache: "no-store" }));
}

export async function jobAction(id: string | number, action: "cancel" | "resume"): Promise<JobStatus> {
  return parse(await fetch(`/api/jobs/${id}/${action}`, { method: "POST" }));
}

export async function getHealth(): Promise<{ translation_configured: boolean; max_upload_mb: number }> {
  return parse(await fetch("/api/health", { cache: "no-store" }));
}
