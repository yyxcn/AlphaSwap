import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import price_feed
import bsc_onchain
import indicators
import ai_analyst
import executor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("alphaswap")

# ── Agent Log (in-memory ring buffer) ────────────────────────────────
from collections import deque

agent_logs: deque = deque(maxlen=200)


def add_log(level: str, msg: str, category: str = "system"):
    """Append a structured log entry visible to the frontend."""
    agent_logs.append({
        "ts": time.time(),
        "level": level,
        "category": category,
        "msg": msg,
    })


# ── State ────────────────────────────────────────────────────────────
latest_state: dict = {
    "current_price": None,
    "indicators": None,
    "whale_data": None,
    "ai_signal": None,
    "last_update": None,
}

# ── Trading Parameters (user-configurable) ───────────────────────────
trading_params: dict = {
    "auto_trade_enabled": True,
    "confidence_threshold": 70,
    "max_trade_percent": 50,
    "rsi_buy_threshold": 30,
    "rsi_sell_threshold": 70,
    "monitor_interval": config.MONITOR_INTERVAL,
    "use_whale_data": True,
    "use_bollinger": True,
    "use_macd": True,
    "use_ma": True,
}

# ── Indicator Overrides (for demo simulation) ────────────────────────
overrides: dict = {
    "enabled": False,
    "rsi": {"value": 45.0, "signal": "neutral"},
    "macd": {"macd": 0.0, "signal_line": 0.0, "histogram": 0.0, "signal": "neutral"},
    "ma": {"sma20": 600.0, "sma50": 598.0, "sma200": None, "ema12": 600.0, "ema26": 599.0, "price": 600.0, "cross": "neutral", "price_vs_sma20": "above"},
    "bollinger": {"upper": 620.0, "middle": 600.0, "lower": 580.0, "bandwidth": 6.0, "pct_b": 0.5, "signal": "neutral"},
    "whale": {"net_flow": "neutral", "exchange_inflow_count": 0, "exchange_outflow_count": 0, "summary": "No overrides active"},
}


# ── Background monitoring loop ───────────────────────────────────────
async def monitor_loop():
    """Main loop: fetch data → compute indicators → AI analysis → execute if signal."""
    while True:
        try:
            logger.info("=== Monitor cycle start ===")
            add_log("info", "Monitor cycle started", "cycle")

            # 1. Price data
            price_data = await price_feed.get_price_data()
            current_price = price_data["current_price"]
            ohlcv = price_data["ohlcv"]
            logger.info(f"BNB/USDT current price: ${current_price}")
            add_log("info", f"BNB/USDT price: ${current_price:.2f}", "price")

            # 2. Technical indicators (1h candles)
            ind = indicators.calculate_all(ohlcv)

            # 3. BSC on-chain whale data
            whale_data = await bsc_onchain.get_whale_transfers()

            # Apply overrides if simulation mode is ON
            if overrides["enabled"]:
                logger.info("[SIMULATION] Using overridden indicator values")
                add_log("warn", "SIMULATION MODE — using overridden indicators", "simulation")
                ind = {
                    "rsi": dict(overrides["rsi"], period=14),
                    "macd": dict(overrides["macd"]),
                    "ma": dict(overrides["ma"]),
                    "bollinger": dict(overrides["bollinger"]),
                }
                whale_data = {
                    "whale_transfers": [],
                    "net_flow": overrides["whale"]["net_flow"],
                    "exchange_inflow_count": overrides["whale"]["exchange_inflow_count"],
                    "exchange_outflow_count": overrides["whale"]["exchange_outflow_count"],
                    "summary": overrides["whale"]["summary"],
                }

            logger.info(f"RSI: {ind['rsi']['value']} ({ind['rsi']['signal']})")
            logger.info(f"Whale net flow: {whale_data['net_flow']} - {whale_data.get('summary','')}")
            add_log("info", f"RSI {ind['rsi']['value']:.1f} ({ind['rsi']['signal']}) | MACD hist {ind['macd']['histogram']:.2f} ({ind['macd']['signal']})", "indicator")
            add_log("info", f"Whale: {whale_data['net_flow']} — {whale_data.get('summary','N/A')}", "whale")

            # 4. AI analysis (pass user params for threshold guidance)
            ai_signal = await ai_analyst.analyze(
                current_price=current_price,
                indicators=ind,
                whale_data=whale_data,
                user_params=trading_params,
            )
            logger.info(f"AI signal: {ai_signal['action']} (confidence: {ai_signal['confidence']}%)")
            logger.info(f"AI reasoning: {ai_signal['reasoning']}")
            ai_level = "success" if ai_signal["action"] == "buy" else "error" if ai_signal["action"] == "sell" else "info"
            add_log(ai_level, f"AI → {ai_signal['action'].upper()} (confidence {ai_signal['confidence']}%)", "ai")
            add_log("info", ai_signal.get("reasoning", "")[:300], "ai_reason")

            # Update state
            latest_state.update({
                "current_price": current_price,
                "indicators": ind,
                "whale_data": whale_data,
                "ai_signal": ai_signal,
                "last_update": time.time(),
            })

            # 5. Auto-execute if confidence threshold met
            if (
                trading_params["auto_trade_enabled"]
                and config.VAULT_ADDRESS
                and ai_signal["action"] in ("buy", "sell")
                and ai_signal.get("confidence", 0) >= trading_params["confidence_threshold"]
            ):
                try:
                    # Default user = agent wallet for demo
                    from web3 import Web3
                    agent_address = Web3(Web3.HTTPProvider(config.BSC_TESTNET_RPC)).eth.account.from_key(config.AGENT_PRIVATE_KEY).address

                    # Calculate trade amount from AI recommendation
                    max_pct = trading_params["max_trade_percent"]
                    pct = min(ai_signal.get("amount_percent", 10), max_pct) / 100
                    balances = executor.get_user_balances(agent_address)

                    if ai_signal["action"] == "buy":
                        usdt_bal = balances["usdt"]
                        amount = int(usdt_bal * pct)
                        if amount > 0:
                            tx = executor.execute_buy(agent_address, amount)
                            logger.info(f"AUTO BUY executed: {amount/1e18:.2f} USDT | TX: {tx['tx_hash']}")
                            add_log("success", f"AUTO BUY executed: {amount/1e18:.2f} USDT → BNB | TX: {tx['tx_hash'][:18]}…", "trade")
                            executor.record_trade(
                                user=agent_address, pair="BNB/USDT", is_buy=True,
                                amount_in=amount, amount_out=0,
                                price=int(current_price * 1e18),
                                ai_reasoning=ai_signal.get("reasoning", "")[:200],
                                confidence=ai_signal["confidence"],
                            )
                    else:  # sell
                        bnb_bal = balances["bnb"]
                        amount = int(bnb_bal * pct)
                        if amount > 0:
                            tx = executor.execute_sell(agent_address, amount)
                            logger.info(f"AUTO SELL executed: {amount/1e18:.4f} BNB | TX: {tx['tx_hash']}")
                            add_log("error", f"AUTO SELL executed: {amount/1e18:.4f} BNB → USDT | TX: {tx['tx_hash'][:18]}…", "trade")
                            executor.record_trade(
                                user=agent_address, pair="BNB/USDT", is_buy=False,
                                amount_in=amount, amount_out=0,
                                price=int(current_price * 1e18),
                                ai_reasoning=ai_signal.get("reasoning", "")[:200],
                                confidence=ai_signal["confidence"],
                            )
                except Exception as trade_err:
                    logger.error(f"Auto-trade error: {trade_err}")
                    add_log("error", f"Trade failed: {trade_err}", "trade")

        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
            add_log("error", f"Monitor error: {e}", "system")

        await asyncio.sleep(trading_params["monitor_interval"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()


# ── FastAPI App ──────────────────────────────────────────────────────
app = FastAPI(title="AlphaSwap Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ───────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    action: str | None = None  # "buy" or "sell" for force mode
    user: str | None = None
    amount: float | None = None  # in USDT for buy, in BNB for sell


class ParamsUpdate(BaseModel):
    auto_trade_enabled: bool | None = None
    confidence_threshold: int | None = None
    max_trade_percent: int | None = None
    rsi_buy_threshold: int | None = None
    rsi_sell_threshold: int | None = None
    monitor_interval: int | None = None
    use_whale_data: bool | None = None
    use_bollinger: bool | None = None
    use_macd: bool | None = None
    use_ma: bool | None = None


# ── Endpoints ────────────────────────────────────────────────────────
@app.get("/api/params")
async def get_params():
    """Get current trading parameters."""
    return trading_params


@app.post("/api/params")
async def update_params(req: ParamsUpdate):
    """Update trading parameters."""
    updates = req.model_dump(exclude_none=True)
    # Clamp values
    if "confidence_threshold" in updates:
        updates["confidence_threshold"] = max(0, min(100, updates["confidence_threshold"]))
    if "max_trade_percent" in updates:
        updates["max_trade_percent"] = max(1, min(100, updates["max_trade_percent"]))
    if "rsi_buy_threshold" in updates:
        updates["rsi_buy_threshold"] = max(0, min(100, updates["rsi_buy_threshold"]))
    if "rsi_sell_threshold" in updates:
        updates["rsi_sell_threshold"] = max(0, min(100, updates["rsi_sell_threshold"]))
    if "monitor_interval" in updates:
        updates["monitor_interval"] = max(10, min(600, updates["monitor_interval"]))

    trading_params.update(updates)
    logger.info(f"Parameters updated: {updates}")
    return trading_params


@app.get("/api/overrides")
async def get_overrides():
    """Get current indicator overrides."""
    return overrides


@app.post("/api/overrides")
async def update_overrides(req: dict):
    """Update indicator overrides for simulation."""
    if "enabled" in req:
        overrides["enabled"] = bool(req["enabled"])
    if "rsi" in req and isinstance(req["rsi"], dict):
        overrides["rsi"].update(req["rsi"])
        # Auto-set signal from value
        v = overrides["rsi"].get("value", 50)
        if v <= trading_params["rsi_buy_threshold"]:
            overrides["rsi"]["signal"] = "oversold"
        elif v >= trading_params["rsi_sell_threshold"]:
            overrides["rsi"]["signal"] = "overbought"
        else:
            overrides["rsi"]["signal"] = "neutral"
    if "macd" in req and isinstance(req["macd"], dict):
        overrides["macd"].update(req["macd"])
        h = overrides["macd"].get("histogram", 0)
        overrides["macd"]["signal"] = "bullish" if h > 0 else "bearish" if h < 0 else "neutral"
    if "ma" in req and isinstance(req["ma"], dict):
        overrides["ma"].update(req["ma"])
    if "bollinger" in req and isinstance(req["bollinger"], dict):
        overrides["bollinger"].update(req["bollinger"])
        pct_b = overrides["bollinger"].get("pct_b", 0.5)
        overrides["bollinger"]["signal"] = "lower_break" if pct_b <= 0 else "upper_break" if pct_b >= 1 else "neutral"
    if "whale" in req and isinstance(req["whale"], dict):
        overrides["whale"].update(req["whale"])

    status = "ACTIVE" if overrides["enabled"] else "INACTIVE"
    logger.info(f"[SIMULATION] Overrides {status}: RSI={overrides['rsi']['value']}, MACD hist={overrides['macd']['histogram']}, Whale={overrides['whale']['net_flow']}")
    return overrides


@app.get("/api/status")
async def get_status():
    """Current price, indicators, whale data, and AI signal."""
    return latest_state


@app.get("/api/trades")
async def get_trades(count: int = 20):
    """Recent trade history from on-chain TradeRegistry."""
    try:
        trades = executor.get_recent_trades(count)
        return {"trades": trades}
    except Exception as e:
        return {"trades": [], "error": str(e)}


@app.post("/api/analyze")
async def manual_analyze(req: AnalyzeRequest):
    """Manually trigger analysis or force buy/sell."""
    try:
        # Get fresh data
        price_data = await price_feed.get_price_data()
        current_price = price_data["current_price"]
        ohlcv = price_data["ohlcv"]
        ind = indicators.calculate_all(ohlcv)
        whale_data = await bsc_onchain.get_whale_transfers()

        # If force buy/sell
        if req.action in ("buy", "sell") and req.user and req.amount:
            ai_signal = await ai_analyst.analyze(
                current_price=current_price,
                indicators=ind,
                whale_data=whale_data,
            )

            amount_wei = int(req.amount * 1e18)

            if req.action == "buy":
                tx_result = executor.execute_buy(req.user, amount_wei)
            else:
                tx_result = executor.execute_sell(req.user, amount_wei)

            # Record trade on-chain
            record_result = executor.record_trade(
                user=req.user,
                pair="BNB/USDT",
                is_buy=(req.action == "buy"),
                amount_in=amount_wei,
                amount_out=0,  # Will be filled from event logs in production
                price=int(current_price * 1e18),
                ai_reasoning=ai_signal.get("reasoning", "Manual trigger"),
                confidence=ai_signal.get("confidence", 0),
            )

            return {
                "action": req.action,
                "ai_signal": ai_signal,
                "tx_result": tx_result,
                "record_result": record_result,
                "price": current_price,
                "indicators": ind,
                "whale_data": whale_data,
            }

        # Analysis only (no execution)
        ai_signal = await ai_analyst.analyze(
            current_price=current_price,
            indicators=ind,
            whale_data=whale_data,
        )

        latest_state.update({
            "current_price": current_price,
            "indicators": ind,
            "whale_data": whale_data,
            "ai_signal": ai_signal,
            "last_update": time.time(),
        })

        return {
            "price": current_price,
            "indicators": ind,
            "whale_data": whale_data,
            "ai_signal": ai_signal,
        }

    except Exception as e:
        logger.error(f"Analyze error: {e}", exc_info=True)
        return {"error": str(e)}


@app.get("/api/portfolio/{address}")
async def get_portfolio(address: str):
    """User portfolio from Vault contract."""
    try:
        balances = executor.get_user_balances(address)
        current_price = latest_state.get("current_price", 0) or 0
        bnb_value_usdt = (balances["bnb"] / 1e18) * current_price
        total_value = (balances["usdt"] / 1e18) + bnb_value_usdt

        return {
            "address": address,
            "usdt": balances["usdt"] / 1e18,
            "bnb": balances["bnb"] / 1e18,
            "bnb_value_usdt": round(bnb_value_usdt, 2),
            "total_value_usdt": round(total_value, 2),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/logs")
async def get_logs(count: int = 100):
    """Recent agent activity logs."""
    entries = list(agent_logs)[-count:]
    return {"logs": entries}


@app.get("/api/network")
async def get_network():
    """BSC Testnet network status."""
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(config.BSC_TESTNET_RPC))
        block = w3.eth.block_number
        gas = w3.eth.gas_price
        return {
            "connected": w3.is_connected(),
            "chain_id": 97,
            "network": "BSC Testnet",
            "block_number": block,
            "gas_price_gwei": round(gas / 1e9, 2),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.get("/api/whales")
async def get_whales():
    """Latest whale transfer data."""
    try:
        data = await bsc_onchain.get_whale_transfers()
        return data
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/ohlcv")
async def get_ohlcv(days: int = 7):
    """OHLCV candlestick data for charting."""
    try:
        ohlcv = await price_feed.get_ohlcv(days)
        records = ohlcv.to_dict(orient="records")
        for r in records:
            r["timestamp"] = r["timestamp"].isoformat()
        return {"ohlcv": records}
    except Exception as e:
        return {"error": str(e)}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
async def serve_frontend():
    """Serve the frontend dashboard."""
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
