# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║   Traffic Flow & Speed Analytics System — Production Dockerfile             ║
# ║                                                                              ║
# ║   Build:   docker build -t traffic-analytics .                              ║
# ║   Run:     docker run -p 8501:8501 -v $(pwd)/data:/app/data traffic-analytics ║
# ║   GPU run: docker run --gpus all -p 8501:8501 traffic-analytics             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Stage 1: dependency builder ───────────────────────────────────────────────
# Use a slim Python base; OpenCV headless needs no X11/display libs.
FROM python:3.11-slim AS builder

# Prevent .pyc files and enable stdout flushing
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages needed to compile / link OpenCV headless & torch
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libglib2.0-0 \
        libgl1-mesa-glx \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Copy requirements first to leverage Docker layer cache.
# Only re-runs pip install when requirements.txt changes.
COPY requirements.txt .

# Install CPU-only torch first (smaller wheel, avoids pulling CUDA libs)
# For GPU deployments: replace the torch line in requirements.txt with
#   --index-url https://download.pytorch.org/whl/cu121
RUN pip install --upgrade pip \
 && pip install --prefix=/install/pkg -r requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu


# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Tell OpenCV to not look for display
    DISPLAY="" \
    # Streamlit server config (overridden by .streamlit/config.toml)
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Copy only the shared libs OpenCV needs at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1-mesa-glx \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        # ffmpeg for VideoWriter mp4v codec support
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install/pkg /usr/local

# ── App directory setup ───────────────────────────────────────────────────────
WORKDIR /app

# Create directories used at runtime
RUN mkdir -p /app/data /app/exports /tmp/streamlit_uploads

# Copy application source files
COPY app.py               .
COPY traffic_pipeline.py  .
COPY database_manager.py  .
COPY .streamlit/          .streamlit/

# Pre-download YOLOv8m weights at build time so first run is instant.
# Comment this out to defer download to runtime (smaller image, ~50 MB).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8m.pt')" \
    || echo "[WARN] YOLOv8 weight pre-download failed — will download at runtime."

# ── Non-root user for security ────────────────────────────────────────────────
RUN groupadd --gid 1001 appuser \
 && useradd  --uid 1001 --gid appuser --no-create-home appuser \
 && chown -R appuser:appuser /app /tmp/streamlit_uploads
USER appuser

# ── Health check ─────────────────────────────────────────────────────────────
# Docker / Kubernetes will mark the container unhealthy if Streamlit is down.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# ── Expose & launch ───────────────────────────────────────────────────────────
EXPOSE 8501

# Use exec form (no shell wrapper) so SIGTERM reaches streamlit directly
ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--server.maxUploadSize=500"]
