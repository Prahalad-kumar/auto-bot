# AUTO-BOT Upgrade

This archive is a complete source tree. The upgrade is not represented only by newly-added files.

## Modified existing files
- `backend/app/main.py` — FastAPI lifespan starts/stops the real-time market-data service; production CORS retained.
- `backend/app/api/routes.py` — authenticated sensitive endpoints, Redis WebSocket endpoint, multi-contract/ATM backtest API, User CRUD, Kite callback compatibility, and audit-log import fix.
- `backend/app/core/security.py` — existing password/JWT security retained.
- `backend/app/workers/celery_app.py` — existing worker configuration retained; legacy scheduled monitor remains as a fallback.
- `backend/app/workers/tasks.py` — existing paper-monitor task retained for fallback/recovery.
- `frontend/src/App.tsx` — production API URL, backend WebSocket connection, live event stream, improved dashboard, and multi-contract/ATM backtest UI.
- `frontend/src/styles.css` — trading-terminal UI, event stream, health cards, contract picker and responsive styling.
- `frontend/vite.config.ts` — correct `loadEnv()` usage for Vite development proxy.
- `frontend/src/vite-env.d.ts` — TypeScript declarations for `import.meta.env.VITE_API_URL`.

## Added
- `backend/app/services/market_data/realtime.py` — KiteTicker tick ingestion, Redis publishing, 5-minute candle aggregation, paper-entry/exit monitoring and real-time events.
- `backend/app/services/market_data/practice.py` — offline tick helper; it never connects to a broker or places an order.

## Safety
- PAPER mode does not call Zerodha order placement.
- Real Zerodha order placement remains guarded by `TRADING_MODE=LIVE` and `LIVE_TRADING_ENABLED=true`.
- Do not commit `.env` or real credentials.

## Validation
- `PYTHONPATH=backend python -m compileall -q backend/app` — passed.
- `PYTHONPATH=backend pytest -q` — 4 passed.
- Frontend dependencies were not installed in the build environment, so `npm run build` must be run in a normal Node environment before deployment.
