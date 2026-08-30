#!/bin/sh

set -e

echo "======================================"
echo "Running Alembic database migrations..."
echo "======================================"

alembic upgrade head

echo "======================================"
echo "Starting Celery worker..."
echo "======================================"

celery -A app.workers.celery_app.celery_app worker --loglevel=INFO --queues=trading &

echo "======================================"
echo "Starting Celery beat..."
echo "======================================"

celery -A app.workers.celery_app.celery_app beat --loglevel=INFO &

echo "======================================"
echo "Starting FastAPI..."
echo "======================================"

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"