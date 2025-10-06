# Dockerfile
FROM python:3.11-slim
WORKDIR /app

# (Optional) system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Spaces expose port 7860
ENV PORT=7860
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "7860"]
