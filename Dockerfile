FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=run.py \
    FLASK_CONFIG=production

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn==23.0.0

COPY . .
RUN chmod +x scripts/docker-entrypoint.sh \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p instance/uploads instance/logs \
    && chown -R appuser:appuser /app/instance
USER appuser

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health').status==200 else 1)"

ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120", "run:app"]
