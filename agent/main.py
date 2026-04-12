import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import price_feed
import bsc_onchain
import indicators
import ai_analyst
import executor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("alphaswap")

# ── State ────────────────────────────────────────────────────────────
latest_state: dict = {
    "current_price": None,
    "indicators": None,
    "whale_data": None,
    "ai_signal": None,
    "last_update": None,
}


# ── Background monitoring loop ───────────────────────────────────────
async def monitor_loop():
    """Main loop: fetch data → compute indicators → AI analysis → execute if signal."""
    while True:
        try:
            logger.info("=== Monitor cycle start ===")

            # 1. Price data
            price_data = await price_feed.get_price_data()
            current_price = price_data["current_price"]
            ohlcv = price_data["ohlcv"]
            logger.info(f"BNB/USDT current price: ${current_price}")

            # 2. Technical indicators (1h candles)
            ind = indicators.calculate_all(ohlcv)
            logger.info(f"RSI: {ind['rsi']['value']} ({ind['rsi']['signal']})")

            # 3. BSC on-chain whale data
            whale_data = await bsc_onchain.get_whale_transfers()
            logger.info(f"Whale net flow: {whale_data['net_flow']} - {whale_data['summary']}")

            # 4. AI analysis
            ai_signal = await ai_analyst.analyze(
                current_price=current_price,
                indicators=ind,
                whale_data=whale_data,
            )
            logger.info(f"AI signal: {ai_signal['action']} (confidence: {ai_signal['confidence']}%)")
            logger.info(f"AI reasoning: {ai_signal['reasoning']}")

            # Update state
            latest_state.update({
                "current_price": current_price,
                "indicators": ind,
                "whale_data": whale_data,
                "ai_signal": ai_signal,
                "last_update": time.time(),
            })

            # 5. Auto-execute if confidence > 70 (disabled by default for safety)
            # To enable: set AUTO_EXECUTE=true in .env
            # if ai_signal["action"] in ("buy", "sell") and ai_signal["confidence"] > 70:
            #     ...

        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)

        await asyncio.sleep(config.MONITOR_INTERVAL)


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


class DepositRequest(BaseModel):
    user: str
    amount: float


# ── Endpoints ────────────────────────────────────────────────────────
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
