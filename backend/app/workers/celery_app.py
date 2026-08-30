from celery import Celery
from app.core.config import settings
celery_app = Celery(
    "autobot",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)
celery_app.conf.task_routes = {"app.workers.tasks.*": {"queue": "trading"}}
celery_app.conf.beat_schedule = {
    "monitor-paper-markets-every-minute": {
        "task": "app.workers.tasks.monitor_paper_market_task",
        "schedule": 60.0,
    },
}
