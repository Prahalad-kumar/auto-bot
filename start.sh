#!/bin/sh

set -e

echo "Starting Celery worker..."
celery -A app.workers.celery_app.celery_app worker --loglevel=INFO --queues=trading &

echo "Starting Celery beat..."
celery -A app.workers.celery_app.celery_app beat --loglevel=INFO &

echo "Starting FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
