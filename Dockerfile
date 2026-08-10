FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/data

WORKDIR /app

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home app && \
    mkdir -p /data && chown app:app /data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app app.py ./
COPY --chown=app:app templates ./templates
COPY --chown=app:app static ./static

USER app
EXPOSE 8000
VOLUME ["/data"]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--access-logfile", "-", "app:app"]
