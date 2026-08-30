from pathlib import Path
import json
from io import BytesIO
from datetime import date
import pandas as pd
from fastapi import File, UploadFile, Query, WebSocket, WebSocketDisconnect
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.session import get_db
from app.models import User, Strategy, Signal, Order, Position, Trade, BrokerConnection, AuditLog
from app.schemas.trading import LoginRequest, Token, StrategyCreate, UserCreate, UserUpdate, UserOut
from app.core.security import hash_password, verify_password, create_access_token
from jose import JWTError, jwt
from app.core.config import settings
from app.services.backtest.engine import BacktestEngine
from app.services.market_data.candles import Candle

api=APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)

def _current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"])
        email = payload.get("sub")
        if not email:
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(func.lower(User.email) == str(email).strip().lower()).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or does not exist")
    return user

def _user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "is_active": user.is_active}

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
    underlying: str = "NIFTY",
    selection_mode: str = Query("ATM", pattern="^(ATM|MANUAL)$"),
    option_instrument_tokens: str | None = None,
    option_tradingsymbols: str | None = None,
    initial_capital: float = 100000,
    quantity: int = 1,
    charge_per_order: float = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(_current_user),
):
    """Run a PAPER backtest using real Kite 5-minute candles.

    ATM mode automatically resolves both CE and PE at the same nearest strike
    for the first underlying price in the requested period. MANUAL mode accepts
    comma-separated instrument tokens and trading symbols.
    """
    if to_date < from_date:
        raise HTTPException(422, "to_date must be on or after from_date")
    if quantity < 1:
        raise HTTPException(422, "quantity must be at least 1")
    mode = selection_mode.upper()
    try:
        kite = _kite_client(db)
        definition = _underlying_definition(underlying)

        # Resolve the index instrument and fetch the underlying candles once.
        instruments = kite.instruments("NSE")
        index_symbol = definition["spot"].split(":", 1)[1]
        index = next((item for item in instruments if item.get("tradingsymbol") == index_symbol), None)
        if not index:
            raise HTTPException(502, f"Could not resolve {underlying} from Kite")
        underlying_candles = _kite_candles(
            kite, int(index["instrument_token"]), from_date, to_date, underlying.upper()
        )

        nfo = [
            item for item in kite.instruments("NFO")
            if item.get("name") == definition["name"]
            and item.get("instrument_type") in {"CE", "PE"}
        ]
        if not nfo:
            raise HTTPException(422, f"No {underlying.upper()} option contracts were returned by Kite")

        selected_contracts: list[dict] = []
        if mode == "ATM":
            # Use the first available underlying close to establish the ATM strike
            # for the selected historical period. Both CE and PE use that same strike.
            spot = float(underlying_candles[0].close)
            expiries = sorted({item["expiry"] for item in nfo if item.get("expiry") is not None})
            valid_expiries = [expiry for expiry in expiries if expiry >= from_date]
            expiry = min(valid_expiries or expiries)
            expiry_contracts = [item for item in nfo if item.get("expiry") == expiry]
            strikes = sorted({float(item["strike"]) for item in expiry_contracts})
            if not strikes:
                raise HTTPException(422, f"No strikes available for {underlying.upper()} expiry {expiry}")
            atm_strike = min(strikes, key=lambda strike: abs(strike - spot))
            selected_contracts = [
                item for item in expiry_contracts
                if float(item["strike"]) == atm_strike and item.get("instrument_type") in {"CE", "PE"}
            ]
            selected_contracts.sort(key=lambda item: item["instrument_type"])
            if {item.get("instrument_type") for item in selected_contracts} != {"CE", "PE"}:
                raise HTTPException(422, f"Could not resolve both ATM CE and PE for {underlying.upper()} {atm_strike}")
        else:
            tokens = [int(x.strip()) for x in (option_instrument_tokens or "").split(",") if x.strip()]
            symbols = [x.strip() for x in (option_tradingsymbols or "").split(",") if x.strip()]
            if not tokens or not symbols or len(tokens) != len(symbols):
                raise HTTPException(422, "MANUAL selection requires matching option_instrument_tokens and option_tradingsymbols")
            by_token = {int(item["instrument_token"]): item for item in nfo}
            by_symbol = {str(item["tradingsymbol"]): item for item in nfo}
            for token, symbol in zip(tokens, symbols):
                item = by_token.get(token) or by_symbol.get(symbol)
                if not item:
                    raise HTTPException(422, f"Option contract not found in Kite instruments: {symbol}")
                selected_contracts.append(item)

        results = []
        for contract in selected_contracts:
            token = int(contract["instrument_token"])
            symbol = str(contract["tradingsymbol"])
            lot_size = int(contract.get("lot_size") or 1)
            # quantity means lots in the API; one lot is the safe default.
            effective_quantity = lot_size * quantity
            options = _kite_candles(kite, token, from_date, to_date, symbol)
            result = BacktestEngine().run(
                underlying_candles,
                options,
                initial_capital=initial_capital,
                quantity=effective_quantity,
                stop_percent=10,
                target_percent=20,
                charge_per_order=charge_per_order,
            )
            results.append({
                "contract": {
                    "instrument_token": token,
                    "tradingsymbol": symbol,
                    "expiry": str(contract.get("expiry")),
                    "strike": float(contract.get("strike") or 0),
                    "option_type": contract.get("instrument_type"),
                    "lot_size": lot_size,
                    "lots": quantity,
                },
                "summary": result["summary"],
                "trades": result["trades"],
                "equity_curve": result["equity_curve"],
            })

        combined_pnl = round(sum(item["summary"]["net_pnl"] for item in results), 2)
        return {
            "selection_mode": mode,
            "underlying": underlying.upper(),
            "from_date": str(from_date),
            "to_date": str(to_date),
            "results": results,
            "combined": {"net_pnl": combined_pnl, "contracts": len(results)},
        }
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
        contracts = [
            item for item in kite.instruments("NFO")
            if item.get("name") == definition["name"] and item.get("instrument_type") in {"CE", "PE"}
        ]
        return [
            {
                "instrument_token": item["instrument_token"],
                "tradingsymbol": item["tradingsymbol"],
                "expiry": str(item["expiry"]),
                "strike": float(item["strike"]),
                "option_type": item["instrument_type"],
                "lot_size": int(item["lot_size"]),
            }
            for item in contracts
        ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not load index option instruments from Kite") from exc

@api.get("/broker/zerodha/option-underlyings")
def zerodha_option_underlyings(current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
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
def zerodha_option_chain(underlying: str = "NIFTY", current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
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
    user=db.query(User).filter(func.lower(User.email)==body.email.strip().lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401,"invalid credentials")
    return Token(access_token=create_access_token(user.email))

@api.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(422, "Email is required")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "A user with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), is_active=body.is_active)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@api.get("/users", response_model=list[UserOut])
def list_users(current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
    # User records are never returned anonymously. Password hashes are never exposed.
    return [_user_out(user) for user in db.query(User).order_by(User.id.asc()).all()]


@api.get("/users/me", response_model=UserOut)
def get_current_user(current_user: User = Depends(_current_user)):
    return _user_out(current_user)


@api.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
    if current_user.id != user_id:
        raise HTTPException(403, "You can only access your own user record")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return _user_out(user)


@api.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
    if current_user.id != user_id:
        raise HTTPException(403, "You can only update your own user record")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if body.email is not None:
        email = body.email.strip().lower()
        duplicate = db.query(User).filter(func.lower(User.email) == email, User.id != user_id).first()
        if duplicate:
            raise HTTPException(409, "A user with this email already exists")
        user.email = email
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return _user_out(user)


@api.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
    if current_user.id != user_id:
        raise HTTPException(403, "You can only delete your own user record")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return None


@api.get("/broker/status")
def broker_status(current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
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
    return RedirectResponse("https://auto-bot-frontend.onrender.com/?broker=connected", status_code=303)

@api.get("/kite/callback", include_in_schema=False)
def legacy_kite_callback(request_token: str, status: str = "success", db: Session = Depends(get_db)):
    """Compatibility callback for the redirect URL already registered in Kite."""
    if status.lower() != "success":
        raise HTTPException(400, "Kite login was not completed successfully")
    _complete_zerodha_callback(request_token, db)
    return RedirectResponse("https://auto-bot-frontend.onrender.com/?broker=connected", status_code=303)

@api.get("/broker/zerodha/quote")
def zerodha_quote(instrument: str = "NSE:NIFTY 50", current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
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
def strategies(current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
    return db.query(Strategy).all()

@api.get("/dashboard/summary")
def dashboard_summary(current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
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
def notifications(current_user: User = Depends(_current_user), db: Session = Depends(get_db)):
    return db.query(AuditLog).filter(AuditLog.event == "PAPER_ORDER_EXECUTED").order_by(AuditLog.timestamp.desc()).limit(20).all()

@api.post("/strategies")
def create_strategy(body: StrategyCreate, current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
    s=Strategy(name=body.name, config=body.config)
    db.add(s); db.commit(); db.refresh(s)
    return s

@api.post("/trading/start")
def start_trading(current_user: User = Depends(_current_user)):
    if settings.TRADING_MODE == "LIVE" and not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(403,"LIVE_TRADING_ENABLED is false")
    return {"status":"STARTED","mode":settings.TRADING_MODE}

@api.post("/trading/stop")
def stop_trading(current_user: User = Depends(_current_user)):
    return {"status":"STOPPED"}

@api.post("/trading/live/enable")
def enable_live(current_user: User = Depends(_current_user)):
    if settings.TRADING_MODE != "LIVE":
        raise HTTPException(403,"Set TRADING_MODE=LIVE first")
    if not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(403,"Set LIVE_TRADING_ENABLED=true first")
    return {"status":"LIVE_ENABLED","warning":"REAL MONEY — LIVE TRADING"}

@api.post("/trading/emergency-stop")
def emergency_stop(current_user: User = Depends(_current_user)):
    return {"status":"HALTED","message":"New signals and order submissions must remain disabled until explicit reset"}

@api.get("/orders")
def orders(current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
    return db.query(Order).order_by(Order.id.desc()).limit(200).all()

@api.get("/positions")
def positions(current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
    return db.query(Position).filter(Position.status=="OPEN").all()

@api.get("/trades")
def trades(current_user: User = Depends(_current_user), db: Session=Depends(get_db)):
    return db.query(Trade).order_by(Trade.id.desc()).limit(200).all()


@api.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Authenticated Redis-backed event stream for the trading terminal."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        if not payload.get("sub"):
            raise ValueError
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return
    await websocket.accept()
    from redis.asyncio import Redis
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe("autobot:events")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                await websocket.send_text(message["data"])
            else:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe("autobot:events")
        await pubsub.close()
        await client.aclose()
