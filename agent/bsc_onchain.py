import aiohttp
from config import BSCSCAN_API_KEY

BSCSCAN_API = "https://api.bscscan.com/api"

# Known exchange hot wallets (partial list for demo)
EXCHANGE_WALLETS = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance Hot Wallet",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance Hot Wallet 2",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance Hot Wallet 3",
    "0x8894e0a0c962cb723c1ef8a1b63d0c8b1b907268": "Binance Hot Wallet 4",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance 8",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance 7",
}

WHALE_THRESHOLD_BNB = 200  # ~$100K+ at ~$600/BNB


async def get_whale_transfers() -> dict:
    """Detect large BNB transfers in recent blocks via BSCScan API."""
    if not BSCSCAN_API_KEY:
        return {
            "whale_transfers": [],
            "net_flow": "unknown",
            "exchange_inflow_count": 0,
            "exchange_outflow_count": 0,
            "summary": "BSCScan API key not configured",
        }

    params = {
        "module": "account",
        "action": "txlist",
        "address": "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance Hot Wallet
        "page": 1,
        "offset": 50,
        "sort": "desc",
        "apikey": BSCSCAN_API_KEY,
    }

    transfers = []
    exchange_inflow = 0
    exchange_outflow = 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BSCSCAN_API, params=params) as resp:
                if resp.status != 200:
                    return {"whale_transfers": [], "net_flow": "error", "summary": f"API error {resp.status}"}
                data = await resp.json()

        if data.get("status") != "1" or not data.get("result"):
            return {"whale_transfers": [], "net_flow": "neutral", "summary": "No recent transactions found"}

        for tx in data["result"]:
            value_bnb = int(tx.get("value", "0")) / 1e18
            if value_bnb < WHALE_THRESHOLD_BNB:
                continue

            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()

            is_inflow = to_addr in EXCHANGE_WALLETS  # deposit to exchange = sell pressure
            is_outflow = from_addr in EXCHANGE_WALLETS  # withdraw from exchange = buy signal

            if is_inflow:
                exchange_inflow += 1
                direction = "exchange_inflow"
            elif is_outflow:
                exchange_outflow += 1
                direction = "exchange_outflow"
            else:
                direction = "unknown"

            transfers.append({
                "hash": tx.get("hash", ""),
                "from": from_addr,
                "to": to_addr,
                "value_bnb": round(value_bnb, 2),
                "direction": direction,
                "timestamp": int(tx.get("timeStamp", 0)),
            })

    except Exception as e:
        return {"whale_transfers": [], "net_flow": "error", "summary": str(e)}

    if exchange_inflow > exchange_outflow:
        net_flow = "sell_pressure"
    elif exchange_outflow > exchange_inflow:
        net_flow = "buy_signal"
    else:
        net_flow = "neutral"

    summary_parts = []
    if exchange_inflow > 0:
        summary_parts.append(f"거래소 입금 {exchange_inflow}건 (매도 압력)")
    if exchange_outflow > 0:
        summary_parts.append(f"거래소 출금 {exchange_outflow}건 (매수 신호)")
    if not summary_parts:
        summary_parts.append("대량 이체 없음")

    return {
        "whale_transfers": transfers[:10],  # max 10
        "net_flow": net_flow,
        "exchange_inflow_count": exchange_inflow,
        "exchange_outflow_count": exchange_outflow,
        "summary": ", ".join(summary_parts),
    }
