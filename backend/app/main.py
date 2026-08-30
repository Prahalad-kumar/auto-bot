from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api, legacy_kite_callback
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The real-time service is event-driven: KiteTicker pushes ticks and Redis
    # fans them out to the dashboard. It does not poll Kite on a millisecond timer.
    from app.services.market_data.realtime import service as realtime_service
    realtime_service.start()
    try:
        yield
    finally:
        realtime_service.stop()


app = FastAPI(title="AUTO BOT", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://auto-bot-frontend.onrender.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api, prefix="/api/v1")
app.add_api_route(
    "/api/kite/callback",
    legacy_kite_callback,
    methods=["GET"],
    include_in_schema=False,
)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "trading_mode": settings.TRADING_MODE}
