from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_jobs, routes_terms
from app.config import get_settings

app = FastAPI(title="Traductor de libros PDF", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(routes_jobs.router)
app.include_router(routes_terms.router)


@app.get("/api/health")
def health():
    st = get_settings()
    # nunca se expone la llave, solo si está configurada
    return {"ok": True, "translation_configured": bool(st.deepseek_api_key), "max_upload_mb": st.max_upload_mb}
