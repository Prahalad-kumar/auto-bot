# AUTO BOT

Production-oriented full-stack algorithmic trading platform for Zerodha Kite Connect with strict BACKTEST/PAPER/LIVE separation.

> **Important:** The supplied specification refers to an attached strategy image/document as the authoritative source, but the supplied text does not contain the actual strategy rules. Therefore `config/strategy.json` intentionally contains a configurable strategy schema with `requires_confirmation: true` rather than inventing entry/exit/SL/target rules.

## Stack
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, Redis, Celery, WebSockets, Alembic, JWT, pytest
- Frontend: React + TypeScript + Vite + React Query + Recharts
- Broker: Zerodha Kite Connect SDK / KiteTicker

## Safety
- Default `TRADING_MODE=PAPER`
- Only `LIVE` may invoke Zerodha order placement
- `LIVE_TRADING_ENABLED=true` is additionally required
- API secrets never reach React
- RiskManager and OrderManager are mandatory gates
- Paper/backtest brokers cannot call live order APIs
- Emergency stop halts new signals and order submissions
- Strategy rules are configuration-driven

## Run
```bash
cp .env.example .env
docker compose up --build
```

Backend: http://localhost:8000/docs
Frontend: http://localhost:5173

Run migrations:
```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Tests:
```bash
docker compose exec backend pytest
```

Compile check:
```bash
docker compose exec backend python -m compileall app
```

Frontend build:
```bash
docker compose exec frontend npm run build
```

## Zerodha
Set `KITE_API_KEY` and `KITE_API_SECRET` in `.env`. Do not commit `.env`.
The login endpoint is `/api/v1/broker/zerodha/login`; the callback is `/api/v1/broker/zerodha/callback`.

Access tokens are session based. Re-authenticate when required.

## Modes
- BACKTEST: historical data + simulated execution only
- PAPER: live market data may be consumed, but simulated execution only
- LIVE: real Zerodha orders, subject to every safety guard

## API highlights
- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `GET /api/v1/broker/zerodha/login`
- `GET /api/v1/broker/zerodha/callback`
- `GET /api/v1/broker/status`
- `GET /api/v1/strategies`
- `POST /api/v1/strategies`
- `POST /api/v1/trading/start`
- `POST /api/v1/trading/stop`
- `POST /api/v1/trading/emergency-stop`
- `POST /api/v1/trading/live/enable`
- `GET /api/v1/orders`
- `GET /api/v1/positions`
- `GET /api/v1/trades`

## Strategy source of truth
Populate `config/strategy.json` with the exact user-provided strategy rules before enabling it. Missing source rules are not guessed.
