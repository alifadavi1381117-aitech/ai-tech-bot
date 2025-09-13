# syntax=docker/dockerfile:1
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Env
ENV PYTHONUNBUFFERED=1     TZ=${TZ:-Europe/Berlin}

# Run
CMD ["python", "bot.py"]
