# ---- Build stage: install dependencies with uv ----
FROM python:3.12-slim AS builder

# This gets an image of uv, better and safer than doing pip install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY . .
RUN uv sync --frozen --no-dev


# ---- Runtime stage ----
FROM python:3.12-slim

# System deps for OpenCV headless + PDF rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the full venv from builder
COPY --from=builder /app /app

# Pre-download the YOLO model into the image so startup is fast
RUN /app/.venv/bin/python -c "from huggingface_hub import hf_hub_download; hf_hub_download('juliozhao/DocLayout-YOLO-DocStructBench', 'doclayout_yolo_docstructbench_imgsz1024.pt')"

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "yoink.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
