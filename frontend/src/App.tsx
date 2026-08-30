import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
const API = `${(import.meta.env.VITE_API_URL || "").replace(/\/$/, "")}/api/v1`;
const tabs = [
  "Dashboard",
  "Markets",
  "Strategies",
  "Backtesting",
  "Signals",
  "Orders",
  "Positions",
  "Trades",
  "Portfolio",
  "Risk",
  "Broker",
  "Logs",
  "Settings",
];
const symbols: Record<string, string> = {
  NIFTY: "NSE:NIFTY 50",
  BANKNIFTY: "NSE:NIFTY BANK",
  FINNIFTY: "NSE:NIFTY FIN SERVICE",
};
async function api(path: string, init: RequestInit = {}) {
  const token = localStorage.getItem("autobot_token");
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(API + path, { ...init, headers });
  if (!r.ok) throw new Error(await r.text());
  return r.status === 204 ? null : r.json();
}
function Table({ rows }: { rows: any[] }) {
  if (!rows?.length) return <p className="muted">No records yet.</p>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c.replaceAll("_", " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{String(r[c] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export default function App() {
  const [token, setToken] = useState(() =>
    localStorage.getItem("autobot_token"),
  );
  const [tab, setTab] = useState("Dashboard");
  const [underlying, setUnderlying] = useState("NIFTY");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [contract, setContract] = useState("");
  const [result, setResult] = useState<any>(null);
  const enabled = !!token;
  const broker = useQuery({
    queryKey: ["broker"],
    queryFn: () => api("/broker/status"),
    enabled,
  });
  const connected = broker.data?.status === "CONNECTED";
  const summary = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api("/dashboard/summary"),
    enabled,
    refetchInterval: 5000,
  });
  const chain = useQuery({
    queryKey: ["chain", underlying],
    queryFn: () => api(`/broker/zerodha/option-chain?underlying=${underlying}`),
    enabled: enabled && connected && tab === "Markets",
    refetchInterval: 2000,
  });
  const contracts = useQuery({
    queryKey: ["contracts", underlying],
    queryFn: () => api(`/broker/zerodha/options?underlying=${underlying}`),
    enabled: enabled && connected && tab === "Backtesting",
    staleTime: 300000,
  });
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api("/strategies"),
    enabled,
  });
  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => api("/orders"),
    enabled,
  });
  const positions = useQuery({
    queryKey: ["positions"],
    queryFn: () => api("/positions"),
    enabled,
  });
  const trades = useQuery({
    queryKey: ["trades"],
    queryFn: () => api("/trades"),
    enabled,
  });
  async function login(e: FormEvent) {
    e.preventDefault();
    const r = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      setError("Invalid email or password");
      return;
    }
    const d = await r.json();
    localStorage.setItem("autobot_token", d.access_token);
    setToken(d.access_token);
  }
  async function logout() {
    await api("/broker/zerodha/logout", { method: "POST" });
    localStorage.removeItem("autobot_token");
    setToken(null);
  }
  async function connect() {
    const d = await api("/broker/zerodha/login");
    location.assign(d.login_url);
  }
  async function backtest(e: FormEvent) {
    e.preventDefault();
    if (!contract) return;
    const [option_instrument_token, option_tradingsymbol, lot_size] =
      contract.split("|");
    const p = new URLSearchParams({
      from_date: fromDate,
      to_date: toDate,
      underlying,
      option_instrument_token,
      option_tradingsymbol,
      quantity: lot_size,
    });
    const r = await fetch(`${API}/backtests/run/zerodha?${p}`, {
      method: "POST",
    });
    const d = await r.json();
    if (!r.ok) {
      setError(d.detail);
      return;
    }
    setResult(d);
  }
  if (!token)
    return (
      <main className="login-page">
        <form className="login-card" onSubmit={login}>
          <h1>AUTO BOT</h1>
          <label>
            Email
            <input
              type="email"
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button>Sign in</button>
        </form>
      </main>
    );
  const selector = (
    <select
      value={underlying}
      onChange={(e) => {
        setUnderlying(e.target.value);
        setContract("");
      }}
    >
      {Object.keys(symbols).map((x) => (
        <option key={x}>{x}</option>
      ))}
    </select>
  );
  let page: any = (
    <section className="panel">
      <h3>{tab}</h3>
      <p className="muted">
        This workspace is being connected to the trading workflow.
      </p>
    </section>
  );
  if (tab === "Dashboard")
    page = (
      <>
        <section className="hero">
          <div>
            <p className="live-label">
              <i /> BOT PERFORMANCE
            </p>
            <h3>Your paper-trading command centre</h3>
            <p>
              Live strategy signals, completed trades, and outcome tracking in
              one place.
            </p>
          </div>
          <div className="hero-orb">
            AUTO
            <br />
            BOT
          </div>
        </section>
        <section className="cards dashboard-cards">
          <div className="card metric calls">
            <small>Bot calls given</small>
            <strong>{summary.data?.bot_calls ?? 0}</strong>
            <span>Generated strategy signals</span>
          </div>
          <div className="card metric success">
            <small>Successful trades</small>
            <strong>{summary.data?.successful_trades ?? 0}</strong>
            <span>Profitable completed trades</span>
          </div>
          <div className="card metric failure">
            <small>Failed trades</small>
            <strong>{summary.data?.failed_trades ?? 0}</strong>
            <span>Breakeven or loss trades</span>
          </div>
          <div className="card metric rate">
            <small>Success rate</small>
            <strong>{summary.data?.win_rate ?? 0}%</strong>
            <span>{summary.data?.total_trades ?? 0} completed trades</span>
          </div>
          <div className="card metric pnl">
            <small>Net P&L</small>
            <strong>₹{summary.data?.net_pnl ?? 0}</strong>
            <span>Realised paper-trading P&L</span>
          </div>
          <div className="card metric positions">
            <small>Open positions</small>
            <strong>{summary.data?.open_positions ?? 0}</strong>
            <span>Mode: PAPER · {underlying}</span>
          </div>
        </section>
        <section className="grid">
          <div className="panel">
            <h3>Bot status</h3>
            <p>
              The dashboard updates every 5 seconds from recorded signals and
              trades.
            </p>
            <div className="status-line">
              <span className="status-dot" />
              Broker {broker.data?.status ?? "CHECKING"}
            </div>
          </div>
          <div className="panel">
            <h3>Performance guide</h3>
            <p>
              <b>Success</b> = net P&L above ₹0.
            </p>
            <p>
              <b>Failed</b> = net P&L at or below ₹0.
            </p>
          </div>
        </section>
      </>
    );
  if (tab === "Markets")
    page = (
      <section className="panel market-panel">
        <div className="page-heading">
          <div>
            <p className="live-label">
              <i /> LIVE MARKET DATA
            </p>
            <h3>Live option chain</h3>
            <p className="muted">
              Real Kite quotes refresh every 2 seconds while the market
              connection is active.
            </p>
          </div>
          {selector}
        </div>
        {!connected ? (
          <p>Connect Kite from Broker to view data.</p>
        ) : chain.isLoading ? (
          <p>Loading option chain…</p>
        ) : chain.error ? (
          <p className="error">Could not load real option data.</p>
        ) : (
          <>
            <section className="cards market-cards">
              <div className="card">
                <small>{underlying} Spot</small>
                <strong>₹{chain.data.spot}</strong>
              </div>
              <div className="card">
                <small>ATM Strike</small>
                <strong>{chain.data.atm_strike}</strong>
              </div>
              <div className="card">
                <small>Nearest Expiry</small>
                <strong>{chain.data.expiry}</strong>
              </div>
            </section>
            <div className="table-wrap">
              <table className="option-chain">
                <thead>
                  <tr>
                    <th>Call LTP</th>
                    <th>Call OI</th>
                    <th>Call Vol</th>
                    <th>Strike</th>
                    <th>Put LTP</th>
                    <th>Put OI</th>
                    <th>Put Vol</th>
                  </tr>
                </thead>
                <tbody>
                  {chain.data.rows.map((r: any) => (
                    <tr className={r.atm ? "atm" : ""} key={r.strike}>
                      <td>{r.ce?.ltp ?? "—"}</td>
                      <td>{r.ce?.oi ?? "—"}</td>
                      <td>{r.ce?.volume ?? "—"}</td>
                      <td>
                        <b>{r.strike}</b>
                      </td>
                      <td>{r.pe?.ltp ?? "—"}</td>
                      <td>{r.pe?.oi ?? "—"}</td>
                      <td>{r.pe?.volume ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    );
  if (tab === "Backtesting")
    page = (
      <section className="panel">
        <div className="page-heading">
          <div>
            <h3>{underlying} option backtest</h3>
            <p className="muted">
              Real Kite historical candles. One actual exchange lot, 10% option
              SL and 20% option target.
            </p>
          </div>
          {selector}
        </div>
        {!connected ? (
          <p className="error">Connect Kite on Broker first.</p>
        ) : (
          <form className="backtest-form" onSubmit={backtest}>
            <label>
              From
              <input
                type="date"
                onChange={(e) => setFromDate(e.target.value)}
                required
              />
            </label>
            <label>
              To
              <input
                type="date"
                onChange={(e) => setToDate(e.target.value)}
                required
              />
            </label>
            <label>
              Contract
              <select
                value={contract}
                onChange={(e) => setContract(e.target.value)}
                required
              >
                <option value="">
                  {contracts.isLoading ? "Loading…" : "Select option"}
                </option>
                {(contracts.data ?? []).map((c: any) => (
                  <option
                    key={c.instrument_token}
                    value={`${c.instrument_token}|${c.tradingsymbol}|${c.lot_size}`}
                  >
                    {c.tradingsymbol} · {c.expiry} · {c.strike} · Lot{" "}
                    {c.lot_size}
                  </option>
                ))}
              </select>
            </label>
            <button>Fetch & run</button>
          </form>
        )}
        {result && (
          <>
            <section className="cards result-cards">
              {Object.entries(result.summary)
                .slice(0, 8)
                .map(([k, v]) => (
                  <div className="card" key={k}>
                    <small>{k.replaceAll("_", " ")}</small>
                    <strong>{String(v ?? "—")}</strong>
                  </div>
                ))}
            </section>
            <h3>Executed option trades</h3>
            <Table rows={result.trades} />
          </>
        )}
      </section>
    );
  if (tab === "Broker")
    page = (
      <section className="panel">
        <h3>Zerodha Kite</h3>
        <p>
          Status: <b>{broker.data?.status ?? "CHECKING"}</b>
        </p>
        <button onClick={connect}>Connect Zerodha</button>
      </section>
    );
  if (tab === "Strategies")
    page = (
      <section className="panel">
        <h3>Strategies</h3>
        <Table rows={strategies.data ?? []} />
      </section>
    );
  if (["Orders", "Positions", "Trades"].includes(tab))
    page = (
      <section className="panel">
        <h3>{tab}</h3>
        <Table
          rows={
            tab === "Orders"
              ? orders.data
              : tab === "Positions"
                ? positions.data
                : trades.data
          }
        />
      </section>
    );
  return (
    <div className="app">
      <aside>
        <div className="brand">
          <span className="brand-mark">◈</span>
          <h1>AUTO BOT</h1>
        </div>
        <p className="mode-label">PAPER WORKSPACE</p>
        {tabs.map((x) => (
          <button
            className={`nav ${tab === x ? "active" : ""}`}
            onClick={() => setTab(x)}
            key={x}
          >
            {x}
          </button>
        ))}
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">TRADING TERMINAL</p>
            <h2>{tab}</h2>
            <span className="paper">PAPER MODE</span>
          </div>
          <div className="header-actions">
            <span
              className={`connection ${connected ? "connected" : "disconnected"}`}
            >
              <i />
              Kite {broker.data?.status ?? "CHECKING"}
            </span>
            <button className="secondary" onClick={logout}>
              Log out
            </button>
          </div>
        </header>
        {page}
      </main>
    </div>
  );
}
