FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# opus-tools (opusenc, ~1 MB): turns the TTS WAV into OGG/Opus voice notes
RUN apt-get update && apt-get install -y --no-install-recommends opus-tools && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd -m -u 10002 waagent && mkdir -p /data && chown -R waagent:waagent /data /app
USER waagent

EXPOSE 8082
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/healthz', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
