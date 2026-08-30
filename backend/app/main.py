from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import api, legacy_kite_callback
from app.core.config import settings

app = FastAPI(title="AUTO BOT", version="1.0.0")

# The React application is hosted separately from FastAPI on Render.
# Keep the exact production origin plus the local Vite origin for development.
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
# Kite redirect URLs are registered independently of the versioned API.  Keep
# this exact path for existing Kite developer-app configurations.
app.add_api_route("/api/kite/callback", legacy_kite_callback, methods=["GET"], include_in_schema=False)

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "trading_mode": settings.TRADING_MODE}
