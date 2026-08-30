from pathlib import Path
import json
from io import BytesIO
from datetime import date
import pandas as pd
from fastapi import File, UploadFile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.session import get_db
from app.models import User, Strategy, Signal, Order, Position, Trade, BrokerConnection
from app.schemas.trading import LoginRequest, Token, StrategyCreate
from app.core.security import hash_password, verify_password, create_access_token
from app.core.config import settings
from app.services.backtest.engine import BacktestEngine
from app.services.market_data.candles import Candle

api=APIRouter()

INDEX_INSTRUMENTS = {
    "NIFTY": {"spot": "NSE:NIFTY 50", "name": "NIFTY"},
    "BANKNIFTY": {"spot": "NSE:NIFTY BANK", "name": "BANKNIFTY"},
    "FINNIFTY": {"spot": "NSE:NIFTY FIN SERVICE", "name": "FINNIFTY"},
}

def _underlying_definition(underlying: str) -> dict:
    result = INDEX_INSTRUMENTS.get(underlying.upper())
    if not result:
        raise HTTPException(422, "Supported indices are NIFTY, BANKNIFTY, and FINNIFTY")
    return result

def _kite_client(db: Session):
    connection = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
    if not connection or connection.status != "CONNECTED" or not connection.access_token:
        raise HTTPException(409, "Zerodha is not connected. Complete the Kite login first.")
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=settings.KITE_API_KEY)
    kite.set_access_token(connection.access_token)
    return kite

def _kite_candles(kite, instrument_token: int, from_date: date, to_date: date, tradingsymbol: str) -> list[Candle]:
    rows = kite.historical_data(instrument_token, from_date, to_date, "5minute", oi=True)
    if not rows:
        raise HTTPException(422, f"Kite returned no 5-minute candles for {tradingsymbol} in this date range")
    return [Candle(timestamp=row["date"], open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]), volume=int(row.get("volume") or 0), oi=row.get("oi"), instrument_token=instrument_token, tradingsymbol=tradingsymbol) for row in rows]

def _read_backtest_candles(upload: UploadFile) -> list[Candle]:
    if not upload.filename or not upload.filename.lower().endswith(".csv"):
        raise HTTPException(422, "Backtest files must be CSV files")
    frame = pd.read_csv(BytesIO(upload.file.read()))
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise HTTPException(422, f"Missing required columns: {', '.join(sorted(missing))}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    if frame.empty:
        raise HTTPException(422, "The CSV contains no valid candles")
    return [Candle(timestamp=row.timestamp.to_pydatetime(), open=float(row.open), high=float(row.high), low=float(row.low), close=float(row.close), volume=int(getattr(row, "volume", 0) or 0), tradingsymbol=str(getattr(row, "tradingsymbol", ""))) for row in frame.itertuples(index=False)]

@api.post("/backtests/run")
def run_backtest(
    underlying_csv: UploadFile = File(...),
    option_csv: UploadFile = File(...),
    initial_capital: float = 100000,
    quantity: int = 1,
    charge_per_order: float = 0,
):
    """Run the configured completed-candle PAPER backtest using real CSV data."""
    try:
        underlying = _read_backtest_candles(underlying_csv)
        options = _read_backtest_candles(option_csv)
        return BacktestEngine().run(underlying, options, initial_capital=initial_capital, quantity=quantity, stop_percent=10, target_percent=20, charge_per_order=charge_per_order)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@api.post("/backtests/run/zerodha")
def run_zerodha_backtest(
    from_date: date,
    to_date: date,
    option_instrument_token: int,
    option_tradingsymbol: str,
    underlying: str = "NIFTY",
    initial_capital: float = 100000,
    quantity: int = 1,
    charge_per_order: float = 0,
    db: Session = Depends(get_db),
):
    """Fetch real 5-minute candles from Kite then run the PAPER-only backtest."""
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    try:
        kite = _kite_client(db)
        definition = _underlying_definition(underlying)
        instruments = kite.instruments("NSE")
        index = next((item for item in instruments if item.get("tradingsymbol") == definition["spot"].split(":", 1)[1]), None)
        if not index:
            raise HTTPException(502, f"Could not resolve {underlying} from Kite")
        underlying_candles = _kite_candles(kite, int(index["instrument_token"]), from_date, to_date, underlying.upper())
        options = _kite_candles(kite, option_instrument_token, from_date, to_date, option_tradingsymbol)
        return BacktestEngine().run(underlying_candles, options, initial_capital=initial_capital, quantity=quantity, stop_percent=10, target_percent=20, charge_per_order=charge_per_order)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Kite historical-data request failed. Check the selected contract, date range, and your data entitlement.") from exc

@api.get("/broker/zerodha/options")
def zerodha_options(underlying: str = "NIFTY", db: Session = Depends(get_db)):
    """List active index option contracts for selecting a direct-data backtest."""
    try:
        kite = _kite_client(db)
        definition = _underlying_definition(underlying)
        contracts = [item for item in kite.instruments("NFO") if item.get("name") == definition["name"] and item.get("instrument_type") in {"CE", "PE"}]
        return [{"instrument_token": item["instrument_token"], "tradingsymbol": item["tradingsymbol"], "expiry": str(item["expiry"]), "strike": item["strike"], "option_type": item["instrument_type"], "lot_size": item["lot_size"]} for item in contracts]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not load NIFTY option instruments from Kite") from exc

@api.get("/broker/zerodha/option-underlyings")
def zerodha_option_underlyings(db: Session = Depends(get_db)):
    """Discover every underlying that currently has an option contract in Kite."""
    try:
        kite = _kite_client(db)
        names = sorted({item.get("name") for item in kite.instruments("NFO") if item.get("name") and item.get("instrument_type") in {"CE", "PE"}})
        return {"underlyings": names}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not load option underlyings from Kite") from exc

@api.get("/broker/zerodha/option-chain")
def zerodha_option_chain(underlying: str = "NIFTY", db: Session = Depends(get_db)):
    """Return a compact live option chain around the current ATM strike."""
    try:
        kite = _kite_client(db)
        definition = _underlying_definition(underlying)
        spot = float(kite.ltp(definition["spot"])[definition["spot"]]["last_price"])
        contracts = [item for item in kite.instruments("NFO") if item.get("name") == definition["name"] and item.get("instrument_type") in {"CE", "PE"}]
        expiry = min(item["expiry"] for item in contracts)
        contracts = [item for item in contracts if item["expiry"] == expiry]
        strikes = sorted({float(item["strike"]) for item in contracts})
        atm = min(strikes, key=lambda strike: abs(strike - spot))
        selected = [item for item in contracts if abs(float(item["strike"]) - atm) <= (strikes[1] - strikes[0] if len(strikes) > 1 else 100) * 5]
        quotes = kite.quote(*[f"NFO:{item['tradingsymbol']}" for item in selected])
        rows = {}
        for item in selected:
            quote = quotes.get(f"NFO:{item['tradingsymbol']}", {})
            record = {"instrument_token": item["instrument_token"], "tradingsymbol": item["tradingsymbol"], "ltp": quote.get("last_price"), "oi": quote.get("oi"), "volume": quote.get("volume"), "lot_size": item["lot_size"]}
            rows.setdefault(float(item["strike"]), {"strike": float(item["strike"]), "atm": float(item["strike"]) == atm})[item["instrument_type"].lower()] = record
        return {"underlying": underlying.upper(), "spot": spot, "expiry": str(expiry), "atm_strike": atm, "rows": [rows[key] for key in sorted(rows)]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not load the live option chain from Kite") from exc

@api.post("/auth/login", response_model=Token)
def login(body: LoginRequest, db: Session=Depends(get_db)):
    user=db.query(User).filter(User.email==body.email.strip().lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401,"invalid credentials")
    return Token(access_token=create_access_token(user.email))

@api.get("/broker/status")
def broker_status(db: Session=Depends(get_db)):
    c=db.query(BrokerConnection).filter(BrokerConnection.broker=="ZERODHA").first()
    return {"broker":"ZERODHA","status":c.status if c else "DISCONNECTED"}

@api.post("/broker/zerodha/logout")
def zerodha_logout(db: Session = Depends(get_db)):
    """Remove the locally stored, session-scoped Kite token."""
    connection = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
    if connection:
        connection.status = "DISCONNECTED"
        connection.access_token = None
        db.commit()
    return {"broker": "ZERODHA", "status": "DISCONNECTED"}

@api.get("/broker/zerodha/login")
def zerodha_login():
    if not settings.KITE_API_KEY:
        raise HTTPException(503,"KITE_API_KEY is not configured")
    from kiteconnect import KiteConnect
    kite=KiteConnect(api_key=settings.KITE_API_KEY)
    return {"login_url": kite.login_url()}

def _complete_zerodha_callback(request_token: str, db: Session) -> None:
    if not settings.KITE_API_KEY or not settings.KITE_API_SECRET:
        raise HTTPException(503,"Kite credentials are not configured")
    from kiteconnect import KiteConnect
    kite=KiteConnect(api_key=settings.KITE_API_KEY)
    data=kite.generate_session(request_token, api_secret=settings.KITE_API_SECRET)
    c=db.query(BrokerConnection).filter(BrokerConnection.broker=="ZERODHA").first()
    if not c:
        c=BrokerConnection(broker="ZERODHA")
        db.add(c)
    c.status="CONNECTED"; c.access_token=data["access_token"]
    db.commit()
    return None

@api.get("/broker/zerodha/callback")
def zerodha_callback(request_token: str, db: Session = Depends(get_db)):
    _complete_zerodha_callback(request_token, db)
    return RedirectResponse("http://localhost:5173/?broker=connected", status_code=303)

@api.get("/kite/callback", include_in_schema=False)
def legacy_kite_callback(request_token: str, status: str = "success", db: Session = Depends(get_db)):
    """Compatibility callback for the redirect URL already registered in Kite."""
    if status.lower() != "success":
        raise HTTPException(400, "Kite login was not completed successfully")
    _complete_zerodha_callback(request_token, db)
    return RedirectResponse("http://localhost:5173/?broker=connected", status_code=303)

@api.get("/broker/zerodha/quote")
def zerodha_quote(instrument: str = "NSE:NIFTY 50", db: Session = Depends(get_db)):
    """Read a live quote only after the user completed Kite's session login."""
    connection = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
    if not connection or connection.status != "CONNECTED" or not connection.access_token:
        raise HTTPException(409, "Zerodha is not connected. Complete the Kite login first.")
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.KITE_API_KEY)
        kite.set_access_token(connection.access_token)
        quote = kite.quote(instrument).get(instrument)
        if not quote:
            raise HTTPException(404, f"Instrument not found: {instrument}")
        return {"instrument": instrument, "quote": quote}
    except HTTPException:
        raise
    except Exception as exc:
        connection.status = "TOKEN_EXPIRED"
        db.commit()
        raise HTTPException(502, "Unable to read Zerodha quote; reconnect your Kite session.") from exc

@api.get("/strategies")
def strategies(db: Session=Depends(get_db)):
    return db.query(Strategy).all()

@api.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """Performance summary from persisted strategy signals and completed trades."""
    calls = db.query(func.count(Signal.id)).scalar() or 0
    successful = db.query(func.count(Trade.id)).filter(Trade.net_pnl > 0).scalar() or 0
    failed = db.query(func.count(Trade.id)).filter(Trade.net_pnl <= 0).scalar() or 0
    total_trades = successful + failed
    net_pnl = db.query(func.coalesce(func.sum(Trade.net_pnl), 0.0)).scalar() or 0.0
    return {
        "bot_calls": calls,
        "successful_trades": successful,
        "failed_trades": failed,
        "total_trades": total_trades,
        "win_rate": round(successful / total_trades * 100, 2) if total_trades else 0,
        "net_pnl": round(float(net_pnl), 2),
        "open_positions": db.query(func.count(Position.id)).filter(Position.status == "OPEN").scalar() or 0,
    }

@api.get("/notifications")
def notifications(db: Session = Depends(get_db)):
    return db.query(AuditLog).filter(AuditLog.event == "PAPER_ORDER_EXECUTED").order_by(AuditLog.timestamp.desc()).limit(20).all()

@api.post("/strategies")
def create_strategy(body: StrategyCreate, db: Session=Depends(get_db)):
    s=Strategy(name=body.name, config=body.config)
    db.add(s); db.commit(); db.refresh(s)
    return s

@api.post("/trading/start")
def start_trading():
    if settings.TRADING_MODE == "LIVE" and not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(403,"LIVE_TRADING_ENABLED is false")
    return {"status":"STARTED","mode":settings.TRADING_MODE}

@api.post("/trading/stop")
def stop_trading():
    return {"status":"STOPPED"}

@api.post("/trading/live/enable")
def enable_live():
    if settings.TRADING_MODE != "LIVE":
        raise HTTPException(403,"Set TRADING_MODE=LIVE first")
    if not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(403,"Set LIVE_TRADING_ENABLED=true first")
    return {"status":"LIVE_ENABLED","warning":"REAL MONEY — LIVE TRADING"}

@api.post("/trading/emergency-stop")
def emergency_stop():
    return {"status":"HALTED","message":"New signals and order submissions must remain disabled until explicit reset"}

@api.get("/orders")
def orders(db: Session=Depends(get_db)):
    return db.query(Order).order_by(Order.id.desc()).limit(200).all()

@api.get("/positions")
def positions(db: Session=Depends(get_db)):
    return db.query(Position).filter(Position.status=="OPEN").all()

@api.get("/trades")
def trades(db: Session=Depends(get_db)):
    return db.query(Trade).order_by(Trade.id.desc()).limit(200).all()
