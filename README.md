# Traductor de libros PDF (EN → ES)

Traduce libros PDF del inglés al español conservando número de páginas, tamaño, imágenes, gráficos,
cajas de color, nombres propios, ISBN, URLs y números.

```
frontend (Next.js :3000) → api (FastAPI :8000) → SQLite (data/app.db) ← worker (pipeline)
pipeline: análisis → protección → traducción (DeepSeek) → reconstrucción → validación
```

## Instalación con Docker (recomendado)

```bash
git clone https://github.com/lore2203/traductor_libros.git
cd traductor_libros
cp .env.example .env        # y pon tu DEEPSEEK_API_KEY (en Windows: copy .env.example .env)
docker compose up --build
```

Requisitos: Git y Docker Desktop. El repositorio es privado: al clonar, inicia sesión con tu cuenta de
GitHub. El archivo `.env` (con la llave) no se sube a GitHub, así que hay que crearlo en cada equipo.

Abre http://localhost:3000. Los PDF originales y traducidos quedan en `data/` (nunca dentro de la BD).

> Sin llave de DeepSeek puedes probar la maquetación con `FAKE_TRANSLATOR=true` en `.env`
> (inserta el texto original alargado un 25 % para simular la expansión del español).

## Desarrollo local (sin Docker)

```bash
python -m venv .venv && .venv/Scripts/pip install -e "backend[dev]"   # Linux/Mac: .venv/bin/pip
cd backend
python -m pytest                                   # pruebas
python -m app.cli analyze libro.pdf --pages 1-5    # ver segmentos detectados
python -m app.cli translate libro.pdf --pages 1-12 --out ../data/outputs/cli   # traducir (usa caché)
python -m app.cli translate libro.pdf --fake       # sin API, solo maquetación
uvicorn app.main:app --reload                      # API
python -m app.worker                               # worker
cd ../frontend && npm install && npm run dev       # interfaz
```

## Configuración (`.env`)

| Variable | Descripción |
|---|---|
| `DEEPSEEK_API_KEY` | Llave de DeepSeek. Nunca se guarda en BD ni se envía al frontend. |
| `DEEPSEEK_MODEL` | Modelo de traducción (`deepseek-flash`). |
| `MAX_UPLOAD_MB` | Tamaño máximo del PDF. |
| `DEEPSEEK_THINKING` | Razonamiento del modelo al traducir: `high` (por defecto, máxima calidad), `low`, `disabled` (unas 2-3 veces más rápido, calidad algo menos pulida). |
| `TRANSLATION_CONCURRENCY` | Solicitudes simultáneas a la API (por defecto 10). |
| `MIN_FONT_SCALE` / `MIN_FONT_SIZE_PT` | Límite de reducción del texto. Solo se pide revisión si el texto queda por debajo del tamaño mínimo legible o se superpone con otro bloque. |
| `FAKE_TRANSLATOR` | `true` para probar sin API. |

## Prueba con el libro de referencia

Copia el PDF a `backend/tests/fixtures/` (está excluido de git) y ejecuta:

```bash
cd backend
python -m app.cli translate tests/fixtures/<libro>.pdf --out ../data/outputs/ref
```

La salida incluye el PDF `<Título en español> (ES).pdf` y `reporte-traduccion.json` con validaciones,
páginas correctas y páginas para revisión.

## Cómo conserva el diseño

- **Texto digital** (PyMuPDF): se analiza carácter a carácter; se detectan párrafos, columnas, filas de índice,
  saltos de línea intencionales (créditos, listas) y fragmentos en otro peso/color/tamaño.
- **Motor de maquetación propio** (`pipeline/layout.py`): coloca cada línea sobre la línea base original, con el
  interlineado, alineación y justificación originales, y aplica **escala horizontal calibrada** para que la fuente
  sustituta ocupe el mismo ancho que la original. Si el español no cabe: amplía la caja hacia espacio libre,
  condensa levemente y reduce el tamaño hasta un mínimo legible; nunca corta texto. Respeta la sangría de cada
  línea original (texto que rodea íconos o imágenes).
- **Fuentes**: se reutiliza la fuente embebida solo si todos los glifos del español tienen contorno real (los
  subconjuntos de InDesign conservan el mapa de caracteres pero vacían los glifos no usados); si no, la misma
  fuente libre cuando existe (Lilita One, Roboto Slab) o una equivalente con el mismo peso y altura de x
  (Rokkitt, Roboto Condensed, Noto) — ver `backend/fonts/`.
- **Texto curvo o inclinado** (rótulos de ruedas, cintas onduladas): se encadenan las letras del texto vectorial
  que siguen una misma trayectoria, se traduce la frase y se dibuja letra a letra sobre la misma curva
  (`pipeline/curved.py`). No necesita OCR.
- **Símbolos** de fuentes Pi/astrológicas, números de página e índice, ISBN, URLs y nombres se conservan intactos.
- **Texto dentro de imágenes** (portadas): OCR con Tesseract (también texto vertical, girando la imagen 90°/270°),
  borrado con inpainting (OpenCV) y texto traducido encima. Se informa como advertencia y solo pide revisión si
  la confianza del reconocimiento es baja. Requiere Docker (Tesseract).
- **Reporte**: no se marcan como problema los textos conservados a propósito (citas «Autor, Título», títulos de
  obras, entradas del índice) ni los números escritos con palabras («1960s» → «años sesenta»). Incluye
  `tiempos_por_etapa_s`.

## Estado

- [x] Fase 1: estructura, BD (SQLite + SQLAlchemy + Alembic), Docker
- [x] Fase 2: pipeline de texto digital (análisis, protección, traducción, reconstrucción, validación) + CLI
- [x] Fase 3: API + worker con cola en SQLite, cancelar/reanudar
- [x] Fase 4: frontend mínimo (carga, progreso, resultado)
- [x] Fase 5 (parcial): OCR con Tesseract + inpainting para texto en imágenes
- [ ] Fase 5 (pendiente): PaddleOCR opcional y DeepSeek Vision para regiones dudosas
- [ ] Fase 6: revisión lado a lado y edición de segmentos
- [ ] Fase 7: pulido
