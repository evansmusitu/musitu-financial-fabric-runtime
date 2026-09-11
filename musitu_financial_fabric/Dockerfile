# syntax=docker/dockerfile:1
# python:3.12.14-slim-bookworm, pinned by multi-platform index digest.
FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ARG MUSITU_BUILD_COMMIT=unknown
LABEL org.opencontainers.image.title="MUSITU Financial Fabric" \
      org.opencontainers.image.revision="$MUSITU_BUILD_COMMIT" \
      org.opencontainers.image.source="https://github.com/evansmusitu/musitu-financial-fabric-runtime"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/musitu

COPY pyproject.toml constraints-ci.txt ./
COPY app ./app

RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    && python -m pip install --no-cache-dir --constraint constraints-ci.txt . \
    && python -m pip check

# Numeric non-root identity keeps the artifact independent of host /etc/passwd.
USER 65532:65532

EXPOSE 8000
STOPSIGNAL SIGTERM

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
