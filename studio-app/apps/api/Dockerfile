# Build-Kontext: Repository-Root, z. B. docker build -f studio-app/apps/api/Dockerfile .
# Modul "api" der Studio-App research-hub: Research-Dashboard (dashboard/serve.py) hinter dem Studio-Gateway.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DASHBOARD_DIR=/app/dashboard

WORKDIR /app

COPY studio-app/apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY dashboard/ /app/dashboard/
COPY studio-app/apps/api/main.py /app/main.py

RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8080

CMD ["python3", "/app/main.py"]
