import aiohttp
import pandas as pd
from web3 import Web3
from config import BSC_MAINNET_RPC, PANCAKE_BNB_USDT_POOL, COINGECKO_API_URL

# PancakeSwap V3 Pool ABI (only slot0)
POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint32", "name": "feeProtocol", "type": "uint32"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


def get_current_price() -> float:
    """Read BNB/USDT price from PancakeSwap V3 slot0 on BSC mainnet (gas-free read call)."""
    w3 = Web3(Web3.HTTPProvider(BSC_MAINNET_RPC))
    pool = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_BNB_USDT_POOL), abi=POOL_ABI)

    slot0 = pool.functions.slot0().call()
    sqrt_price_x96 = slot0[0]

    # Price calculation from sqrtPriceX96
    # price = (sqrtPriceX96 / 2^96)^2
    # For BNB/USDT pool: token0=BNB(18dec), token1=USDT(18dec)
    # price = token1/token0 = USDT per BNB
    price = (sqrt_price_x96 / (2**96)) ** 2

    # If price is very small (< 1), it means token ordering is reversed
    if price < 1:
        price = 1 / price

    return round(price, 2)


async def get_ohlcv(days: int = 7) -> pd.DataFrame:
    """Fetch BNB/USDT 1-hour OHLCV from CoinGecko for the past N days."""
    url = f"{COINGECKO_API_URL}/coins/binancecoin/ohlc"
    params = {"vs_currency": "usd", "days": days}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise Exception(f"CoinGecko API error: {resp.status}")
            data = await resp.json()

    # CoinGecko OHLC returns [timestamp, open, high, low, close]
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["volume"] = 0  # CoinGecko OHLC endpoint doesn't include volume
    return df


async def get_price_data(days: int = 7) -> dict:
    """Get both current price and OHLCV data."""
    current_price = get_current_price()
    ohlcv = await get_ohlcv(days)
    return {
        "current_price": current_price,
        "ohlcv": ohlcv,
    }
