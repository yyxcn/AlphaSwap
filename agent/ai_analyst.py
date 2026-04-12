import json
import re
import anthropic
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SYSTEM_PROMPT = """당신은 BNB/USDT 암호화폐 트레이딩 AI 애널리스트입니다.
기술적 지표(1시간봉 기준)와 BSC 온체인 고래 데이터를 종합 분석하여 매매 판단을 내립니다.

분석 원칙:
1. 단일 지표에 의존하지 말고 여러 지표의 컨플루언스(confluence)를 확인하세요.
2. BSC 온체인 고래 데이터는 시장 심리의 선행 지표로 활용하세요.
3. 확신이 낮으면 hold를 권장하세요.
4. 리스크 관리: 한 번에 포트폴리오의 50%를 초과하는 매매는 피하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
    "action": "buy" | "sell" | "hold",
    "confidence": 0~100,
    "amount_percent": 1~50,
    "reasoning": "한국어로 판단 근거 (기술 지표 + 고래 데이터 분석 포함)",
    "indicators_summary": {
        "rsi": "과매도/중립/과매수 + 수치",
        "macd": "강세/중립/약세 + 히스토그램 방향",
        "ma": "골든크로스/데드크로스/중립 + 가격 위치",
        "bollinger": "하단이탈/중립/상단이탈 + %B값",
        "whale": "매수신호/중립/매도압력 + 요약"
    }
}"""


async def analyze(
    current_price: float,
    indicators: dict,
    whale_data: dict,
    recent_trades: list | None = None,
    portfolio: dict | None = None,
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

    user_prompt = f"""현재 BNB/USDT 분석을 요청합니다.

## 현재가
{current_price} USDT

## 기술적 지표 (1시간봉 기준)

### RSI (14기간)
- 값: {indicators['rsi']['value']}
- 신호: {indicators['rsi']['signal']}

### MACD (12/26/9)
- MACD: {indicators['macd']['macd']}
- 시그널: {indicators['macd']['signal_line']}
- 히스토그램: {indicators['macd']['histogram']}
- 신호: {indicators['macd']['signal']}

### 이동평균선
- SMA(20h): {indicators['ma']['sma20']}
- SMA(50h): {indicators['ma']['sma50']}
- SMA(200h): {indicators['ma']['sma200']}
- EMA(12h): {indicators['ma']['ema12']}
- EMA(26h): {indicators['ma']['ema26']}
- 크로스: {indicators['ma']['cross']}
- 가격 vs SMA20: {indicators['ma']['price_vs_sma20']}

### 볼린저밴드 (20h, 2σ)
- 상단: {indicators['bollinger']['upper']}
- 중간: {indicators['bollinger']['middle']}
- 하단: {indicators['bollinger']['lower']}
- %B: {indicators['bollinger']['pct_b']}
- 신호: {indicators['bollinger']['signal']}

## BSC 온체인 고래 데이터
- 넷플로우: {whale_data.get('net_flow', 'unknown')}
- 거래소 입금(매도 압력): {whale_data.get('exchange_inflow_count', 0)}건
- 거래소 출금(매수 신호): {whale_data.get('exchange_outflow_count', 0)}건
- 요약: {whale_data.get('summary', 'N/A')}
"""

    if recent_trades:
        user_prompt += "\n## 최근 매매 이력\n"
        for t in recent_trades[-5:]:
            side = "매수" if t.get("is_buy") else "매도"
            user_prompt += f"- {side}: {t.get('amount_in')} → {t.get('amount_out')} (신뢰도 {t.get('confidence')}%)\n"

    if portfolio:
        user_prompt += f"\n## 현재 포트폴리오\n- USDT: {portfolio.get('usdt', 0)}\n- BNB: {portfolio.get('bnb', 0)}\n"

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
