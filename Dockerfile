FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROFL_REPORT_ROOT=/var/lib/rofl-analysis/reports \
    ROFL_UPLOAD_ROOT=/var/lib/rofl-analysis/uploads \
    ROFL_CACHE_ROOT=/var/lib/rofl-analysis/cache

WORKDIR /app
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /var/lib/rofl-analysis/reports /var/lib/rofl-analysis/uploads /var/lib/rofl-analysis/cache \
    && chown -R 10001:10001 /app /var/lib/rofl-analysis

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "rofl_analyzer.api:app", "--host", "0.0.0.0", "--port", "8080"]
