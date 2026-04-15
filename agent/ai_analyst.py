import json
import re
import anthropic
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SYSTEM_PROMPT = """You are a BNB/USDT cryptocurrency trading AI analyst.
You synthesize technical indicators (1-hour candles) and BSC on-chain whale data to make trading decisions.

Analysis principles:
1. Do not rely on a single indicator — confirm confluence across multiple indicators.
2. Use BSC on-chain whale data as a leading indicator of market sentiment.
3. If conviction is low, recommend hold.
4. Risk management: never exceed 50% of the portfolio in a single trade.
5. Consider recent trade history and current portfolio — avoid repeated trades in the same direction if already sufficiently positioned.

Respond ONLY in the following JSON format:
{
    "action": "buy" | "sell" | "hold",
    "confidence": 0~100,
    "amount_percent": 1~50,
    "reasoning": "Reasoning in English (include technical indicator + whale data analysis)",
    "indicators_summary": {
        "rsi": "oversold/neutral/overbought + value",
        "macd": "bullish/neutral/bearish + histogram direction",
        "ma": "golden_cross/death_cross/neutral + price position",
        "bollinger": "lower_break/neutral/upper_break + %B value",
        "whale": "buy_signal/neutral/sell_pressure + summary"
    }
}"""


async def analyze(
    current_price: float,
    indicators: dict,
    whale_data: dict,
    recent_trades: list | None = None,
    portfolio: dict | None = None,
    user_params: dict | None = None,
) -> dict:
    """Send indicators + on-chain data to Claude for trading analysis."""
    if not client:
        return {
            "action": "hold",
            "confidence": 0,
            "amount_percent": 0,
            "reasoning": "Anthropic API key not configured",
            "indicators_summary": {},
        }

    user_prompt = f"""Requesting BNB/USDT analysis.

## Current Price
{current_price} USDT

## Technical Indicators (1H candles)

### RSI (14-period)
- Value: {indicators['rsi']['value']}
- Signal: {indicators['rsi']['signal']}

### MACD (12/26/9)
- MACD: {indicators['macd']['macd']}
- Signal line: {indicators['macd']['signal_line']}
- Histogram: {indicators['macd']['histogram']}
- Signal: {indicators['macd']['signal']}

### Moving Averages
- SMA(20h): {indicators['ma']['sma20']}
- SMA(50h): {indicators['ma']['sma50']}
- SMA(200h): {indicators['ma']['sma200']}
- EMA(12h): {indicators['ma']['ema12']}
- EMA(26h): {indicators['ma']['ema26']}
- Cross: {indicators['ma']['cross']}
- Price vs SMA20: {indicators['ma']['price_vs_sma20']}

### Bollinger Bands (20h, 2σ)
- Upper: {indicators['bollinger']['upper']}
- Middle: {indicators['bollinger']['middle']}
- Lower: {indicators['bollinger']['lower']}
- %B: {indicators['bollinger']['pct_b']}
- Signal: {indicators['bollinger']['signal']}

## 24H Volume
- BNB volume: {indicators.get('volume_24h', 'N/A')} BNB

## BSC On-chain Whale Data
- Net flow: {whale_data.get('net_flow', 'unknown')}
- Exchange inflow (sell pressure): {whale_data.get('exchange_inflow_count', 0)} transfers
- Exchange outflow (buy signal): {whale_data.get('exchange_outflow_count', 0)} transfers
- Summary: {whale_data.get('summary', 'N/A')}
"""

    if recent_trades:
        import time as _time
        user_prompt += "\n## Recent Trade History\n"
        for t in recent_trades[-5:]:
            side = "BUY" if t.get("is_buy") else "SELL"
            ts = t.get("timestamp", 0)
            mins_ago = int((_time.time() - ts) / 60) if ts else "unknown"
            user_prompt += f"- {side}: {t.get('amount_in')} → {t.get('amount_out')} (confidence {t.get('confidence')}%) — {mins_ago} min ago\n"

    if portfolio:
        user_prompt += f"\n## Current Portfolio\n- USDT: {portfolio.get('usdt', 0)}\n- BNB: {portfolio.get('bnb', 0)}\n"

    if user_params:
        user_prompt += f"""
## User Parameters (use as guidelines)
- RSI buy threshold: consider buying at or below {user_params.get('rsi_buy_threshold', 30)}
- RSI sell threshold: consider selling at or above {user_params.get('rsi_sell_threshold', 70)}
- Max trade size: {user_params.get('max_trade_percent', 50)}% of portfolio
- Use whale data: {'yes' if user_params.get('use_whale_data', True) else 'no (ignore)'}
- Use Bollinger Bands: {'yes' if user_params.get('use_bollinger', True) else 'no (ignore)'}
- Use MACD: {'yes' if user_params.get('use_macd', True) else 'no (ignore)'}
- Use Moving Averages: {'yes' if user_params.get('use_ma', True) else 'no (ignore)'}
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text

    # Parse JSON (handle ```json ... ``` wrapping)
    json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "action": "hold",
            "confidence": 0,
            "amount_percent": 0,
            "reasoning": f"Failed to parse AI response: {raw[:200]}",
            "indicators_summary": {},
        }

    return result
