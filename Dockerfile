# TradeLead Hunter — 云服务器 / 容器部署
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEADHUNTER_HOST=0.0.0.0 \
    LEADHUNTER_PORT=8866 \
    LEADHUNTER_DATA=/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY config.yaml .
COPY start.sh .
RUN chmod +x start.sh && mkdir -p /data

EXPOSE 8866
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8866/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8866"]
