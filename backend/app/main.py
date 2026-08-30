from fastapi import FastAPI
from app.api.routes import api, legacy_kite_callback
from app.core.config import settings

app = FastAPI(title="AUTO BOT", version="1.0.0")
app.include_router(api, prefix="/api/v1")
# Kite redirect URLs are registered independently of the versioned API.  Keep
# this exact path for existing Kite developer-app configurations.
app.add_api_route("/api/kite/callback", legacy_kite_callback, methods=["GET"], include_in_schema=False)

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "trading_mode": settings.TRADING_MODE}
