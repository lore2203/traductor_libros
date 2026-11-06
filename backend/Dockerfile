FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Tesseract (eng+spa), OCRmyPDF y fuentes libres Noto
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa \
        ocrmypdf ghostscript \
        fonts-noto-core fonts-noto-mono \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias primero (capa en caché mientras no cambie pyproject.toml)
COPY pyproject.toml ./
RUN pip install --no-cache-dir $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")

COPY . .

ENV FONTS_DIRS=/app/fonts:/usr/share/fonts/truetype/noto
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
