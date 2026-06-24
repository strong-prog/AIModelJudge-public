# AIModelJudge — multi-stage Docker build
# Stage 1: build frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/web-react
COPY web-react/package.json web-react/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web-react/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.12-slim
LABEL org.opencontainers.image.title="AIModelJudge"
LABEL org.opencontainers.image.description="AI-powered code analysis platform"
LABEL org.opencontainers.image.version="1.5.0"

RUN groupadd -r appuser -g 1000 && useradd -r -g appuser -u 1000 -m appuser

WORKDIR /app

# Install runtime deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir --no-deps . && \
    pip install --no-cache-dir \
    fastapi==0.137.2 \
    "uvicorn[standard]==0.49.0" \
    starlette==1.3.1 \
    python-multipart==0.0.32 \
    sse-starlette==3.4.4 \
    "passlib[bcrypt]==1.7.4" \
    bcrypt==3.2.2 \
    cryptography==44.0.0 \
    "PyJWT[crypto]==2.13.0" \

    python-dotenv==1.2.2 \
    httpx==0.28.1 \
    httpx-sse==0.4.3 \
    aiogram==3.29.0 \
    PyYAML==6.0.1 \
    Jinja2==3.1.6 \
    pydantic==2.13.4 \
    pydantic-settings==2.14.1 \
    aiofiles==25.1.0 \
    Pillow==10.2.0 \
    websockets==16.0

# Copy backend + shared code
COPY web/ ./web/
COPY services/shared/ ./services/shared/

# Copy frontend build
COPY --from=frontend-builder /app/web-react/dist ./web-react/dist

# Data dir
RUN mkdir -p /app/data /home/appuser/.hermes-aimodeljudge && \
    chown -R appuser:appuser /app /home/appuser/.hermes-aimodeljudge

USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/web:/app/services/shared
ENV AMJ_WEB_HOST=0.0.0.0
ENV AMJ_WEB_PORT=9651

EXPOSE 9651

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9651/health')" || exit 1

CMD ["python3", "web/main.py"]
