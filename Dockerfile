FROM python:3.11-slim

WORKDIR /app

# Chromium system dependencies for Debian Trixie
# (playwright --with-deps fails on Trixie due to renamed font packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 \
    libxcb1 libxkbcommon0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 \
    libasound2t64 libatspi2.0-0 \
    fonts-liberation fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser (no --with-deps, we handled deps above)
RUN playwright install chromium

# Application code
COPY backend/      backend/
COPY dian_core/    dian_core/
COPY dian_processes/ dian_processes/
COPY frontend/     frontend/

RUN mkdir -p /data/dian-jobs

EXPOSE 8000

# Single worker — in-memory job store must not be shared across processes
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
