# AlphaSwap Internal Reference

니가 발표/데모/디버깅할 때 보는 문서. README보다 훨씬 자세함.

---

## 1. 전체 흐름 (60초 루프)

```
main.py monitor_loop() — 60초마다 반복

1. price_feed.get_price_data()
   ├─ PancakeSwap V3 BNB/USDT 풀 slot0() → sqrtPriceX96 → 현재가 계산
   │   (BSC 메인넷 read-only, 가스비 0)
   │   풀 주소: 0x36696169C63e42cd08ce11f5deeBbCeBae652050
   │   공식: price = (sqrtPriceX96 / 2^96)^2 × 10^(18-18)
   │   token0=BNB, token1=USDT이므로 1/price 해서 USDT 기준으로 변환
   │
   └─ Binance API → 41일치 1시간봉 984개 캔들 + 볼륨
      GET /api/v3/klines?symbol=BNBUSDT&interval=1h&limit=984
      → DataFrame [timestamp, open, high, low, close, volume]

2. indicators.calculate_all(ohlcv)
   ├─ RSI(14) — pandas_ta.rsi(close, 14)
   │   < 30: oversold (매수 신호)
   │   > 70: overbought (매도 신호)
   │
   ├─ MACD(12, 26, 9) — pandas_ta.macd(close, 12, 26, 9)
   │   histogram > 0: bullish
   │   histogram < 0: bearish
   │   MACD선이 시그널선 위로 교차: 골든크로스
   │
   ├─ MA — SMA(20, 50, 200), EMA(12, 26)
   │   SMA(200): 41일 데이터로 계산 가능 (984 캔들 > 200)
   │   EMA12 > EMA26: golden_cross (매수)
   │   EMA12 < EMA26: death_cross (매도)
   │   price > SMA20: above (상승 추세)
   │
   └─ Bollinger Bands(20, 2σ) — pandas_ta.bbands(close, 20, 2)
      %B < 0: lower_break (과매도, 매수 신호)
      %B > 1: upper_break (과매수, 매도 신호)
      컬럼 순서: BBL(0), BBM(1), BBU(2), BBB(3), BBP(4)

3. bsc_onchain.get_whale_transfers()
   BSCScan API로 바이낸스 핫월렛 대량 이체 감지
   ├─ 바이낸스 핫월렛: 0x8894E0a0c962CB723c1ef8a1Bc6A4387c6d4d5e0 외 3개
   │   (하드코딩 — EXCHANGE_WALLETS dict)
   ├─ 임계값: 200 BNB 이상만 감지
   ├─ 거래소 → 외부 = outflow (매수 신호, 고래가 빼감)
   └─ 외부 → 거래소 = inflow (매도 압력, 고래가 팔려고 넣음)

4. ai_analyst.analyze()
   Claude API (claude-sonnet-4-20250514)에 전체 데이터 전달
   ├─ 시스템 프롬프트: 한국어 트레이딩 AI 역할
   ├─ 유저 프롬프트: 현재가 + RSI/MACD/MA/BB + 고래 데이터 + user_params
   ├─ 응답 포맷: JSON { action, confidence, amount_percent, reasoning, indicators_summary }
   └─ user_params 전달 시 RSI 임계값, 지표 토글 등 참고하여 판단

5. 자동매매 실행 조건
   trading_params["auto_trade_enabled"] == True
   AND config.VAULT_ADDRESS 존재
   AND action in ("buy", "sell")
   AND confidence >= trading_params["confidence_threshold"] (기본 70)

   실행:
   ├─ executor.execute_buy(user, amount_wei)
   │   Vault.executeBuy(user, usdtAmount) → MockRouter.swapExactTokensForTokens()
   ├─ executor.execute_sell(user, amount_wei)
   │   Vault.executeSell(user, bnbAmount) → MockRouter.swapExactTokensForTokens()
   └─ executor.record_trade() → TradeRegistry.recordTrade()
```

---

## 2. 스마트 컨트랙트 상세

### 배포된 주소 (BSC Testnet)

| Contract | Address |
|----------|---------|
| Vault | `0x28530C53E3BC3f038e2D93663862C11B805D50F9` |
| TradeRegistry | `0xBA4771F22F70121563CEA254458309c7e7960E34` |
| MockRouter | `0x3B4Fd1d4B33EBd1cfD9AB10Bf58251fc7736A62E` |
| MockUSDT | `0xbe86CE4116f922bB0e226773377E81844e7F7Bc9` |
| MockBNB | `0xa4E587Ab0729b6FBb8f6E68436dCCb48Ca5B4712` |

### Vault.sol
```
deposit(amount)         — USDT 예치 (approve 먼저)
withdraw(amount)        — USDT 출금
executeBuy(user, amt)   — [agent only] USDT→BNB 스왑
executeSell(user, amt)  — [agent only] BNB→USDT 스왑
quoteBalances[user]     — USDT 잔고
baseBalances[user]      — BNB 잔고
authorizeAgent(addr)    — [owner only] 에이전트 권한 부여
```

### MockRouter.sol
```
setRate(rate)                           — [owner only] 1 BNB = rate USDT (기본 600)
swapExactTokensForTokens(amt, ...)      — 토큰 교환 (rate 기반)
getAmountsOut(amt, path)                — 예상 교환량 조회
```
- USDT→BNB: amountOut = amountIn * 1e18 / rate
- BNB→USDT: amountOut = amountIn * rate / 1e18
- 역방향 rate 자동 계산

### TradeRegistry.sol
```
recordTrade(user, pair, isBuy, amtIn, amtOut, price, reasoning, confidence)
getRecentTrades(count)  — 최근 N건
getUserTrades(user)     — 특정 유저 매매 기록
tradeCount()            — 총 매매 건수
```

### Deploy.s.sol 배포 순서
1. MockUSDT (decimals 18) + MockBNB (decimals 18)
2. MockRouter → setRate(600e18) → USDT/BNB approve → 유동성 mint
3. Vault(usdt, bnb, router) → authorizeAgent(agent)
4. TradeRegistry → authorizeRecorder(agent)
5. Agent에게 10,000 USDT mint (테스트용)

---

## 3. API 엔드포인트 상세

### GET /api/status
```json
{
  "current_price": 597.67,
  "indicators": {
    "rsi": {"value": 43.52, "signal": "neutral", "period": 14},
    "macd": {"macd": -3.15, "signal_line": -1.19, "histogram": -1.96, "signal": "bearish"},
    "ma": {"sma20": 601.45, "sma50": 598.2, "sma200": 603.77, "ema12": 599.1, "ema26": 600.3, "cross": "death_cross", "price_vs_sma20": "below"},
    "bollinger": {"upper": 615.2, "middle": 601.45, "lower": 587.7, "bandwidth": 4.57, "pct_b": 0.24, "signal": "neutral"}
  },
  "whale_data": {"net_flow": "neutral", "exchange_inflow_count": 0, "exchange_outflow_count": 0, "summary": "..."},
  "ai_signal": {"action": "hold", "confidence": 65, "amount_percent": 0, "reasoning": "...", "indicators_summary": {...}},
  "last_update": 1776066798.67
}
```

### POST /api/params
```json
// Request
{"confidence_threshold": 60, "rsi_buy_threshold": 35, "use_whale_data": false}

// Response: 업데이트된 전체 파라미터
{"auto_trade_enabled": true, "confidence_threshold": 60, ...}
```
클램핑: confidence 0~100, max_trade 1~100, rsi 0~100, interval 10~600

### POST /api/overrides
```json
// Request — 시뮬레이션 활성화 + Strong Buy 세팅
{
  "enabled": true,
  "rsi": {"value": 22},
  "macd": {"histogram": 5.0},
  "bollinger": {"pct_b": 0.05},
  "whale": {"net_flow": "outflow", "exchange_outflow_count": 5, "summary": "Strong whale accumulation"}
}

// 자동 파생:
// RSI 22 < rsi_buy_threshold(30) → signal: "oversold"
// MACD histogram 5.0 > 0 → signal: "bullish"
// Bollinger pct_b 0.05 (0 < x < 1) → signal: "neutral"
```

### POST /api/analyze
```json
// 분석만
{}

// Force Buy
{"action": "buy", "user": "0x...", "amount": 100.0}

// Force Sell
{"action": "sell", "user": "0x...", "amount": 0.5}
```

### GET /api/network
```json
{"connected": true, "chain_id": 97, "network": "BSC Testnet", "block_number": 101394903, "gas_price_gwei": 0.1}
```

### GET /api/logs
```json
{
  "logs": [
    {"ts": 1776066787.94, "level": "info", "category": "cycle", "msg": "Monitor cycle started"},
    {"ts": 1776066788.71, "level": "info", "category": "price", "msg": "BNB/USDT price: $597.67"},
    {"ts": 1776066789.63, "level": "info", "category": "indicator", "msg": "RSI 43.5 (neutral) | MACD hist -1.96 (bearish)"},
    {"ts": 1776066789.63, "level": "info", "category": "whale", "msg": "Whale: neutral — No recent transactions found"},
    {"ts": 1776066798.67, "level": "info", "category": "ai", "msg": "AI → HOLD (confidence 65%)"},
    {"ts": 1776066798.67, "level": "info", "category": "ai_reason", "msg": "현재 BNB는 중립적인 기술적 상황에서..."}
  ]
}
```
카테고리: cycle, price, indicator, whale, ai, ai_reason, trade, simulation, system

---

## 4. 프론트엔드 구조

### 탭 시스템
```
사이드바 (좌측 고정)
├─ Sentinel    → #view-analytics  (showTab('analytics'))
├─ Parameters  → #view-params     (showTab('params'))
├─ Simulation  → #view-simulation (showTab('simulation'))
├─ Agent Log   → #view-logs       (showTab('logs'))
├─ [Network Status]  — BSC Testnet 블록/가스/연결
└─ [Vault Balance]   — 지갑 연결 시 표시
```

### 자동 새로고침 주기
| 데이터 | 함수 | 주기 |
|--------|------|------|
| 상태/지표/AI | fetchStatus() | 30초 |
| OHLCV 캔들 | fetchOHLCV() | 120초 |
| 고래 데이터 | fetchWhales() | 60초 |
| 네트워크 | fetchNetwork() | 15초 |
| 에이전트 로그 | fetchLogs() | 10초 (로그 탭일 때만) |

### MetaMask / Rabby 연결
connectWallet() → BSC Testnet 자동 추가 (chainId 0x61)
→ 연결 후 POST /api/set-user → AI가 해당 지갑으로 자동매매
→ loadPortfolio() → Vault 잔고 사이드바에 표시 (5초 자동 새로고침)
→ Mint Test USDT / Deposit to Vault 버튼 활성화

### 차트 (lightweight-charts)
- candlestickSeries: OHLCV 1시간봉 (41일, 984캔들, KST 시간대)
- sma20Series: SMA(20) 파란 라인
- sma50Series: SMA(50) 보라 라인
- sma200Series: SMA(200) 흰색 점선
- bbUpperSeries / bbLowerSeries: 볼린저 밴드 (녹색 점선)
- volumeSeries: 거래량 히스토그램 (하단)

---

## 5. AI 판단 기준 (핵심)

### AI는 뭘 보고 판단하는가?

규칙 기반이 아님. Claude한테 모든 데이터를 텍스트로 넘기고 **종합 판단**을 시킴.
단일 지표로 결정하는 게 아니라 여러 지표의 **컨플루언스(confluence)**를 봄.

AI에게 전달되는 데이터:
```
1. 현재가 (PancakeSwap V3 실시간)
2. RSI(14) — 값 + 신호 (oversold/neutral/overbought)
3. MACD(12/26/9) — MACD선, 시그널선, 히스토그램, 신호
4. 이동평균 — SMA(20/50/200), EMA(12/26), 크로스 상태, 가격 위치
5. 볼린저밴드 — 상/중/하단, %B, 신호
6. BSC 고래 데이터 — 거래소 입출금 건수, 넷플로우, 요약
7. 사용자 파라미터 — RSI 임계값, 지표 토글, 최대 매매 비율
```

### AI 시스템 프롬프트 핵심 원칙 (ai_analyst.py L8~)
```
1. 단일 지표에 의존하지 말고 여러 지표의 컨플루언스를 확인
2. BSC 온체인 고래 데이터는 시장 심리의 선행 지표로 활용
3. 확신이 낮으면 hold를 권장
4. 리스크 관리: 한 번에 포트폴리오의 50%를 초과하는 매매 금지
```

### BUY 판단 기준 (AI가 종합적으로 고려)
| 지표 | 매수 시그널 | 가중치(AI 재량) |
|------|-----------|---------------|
| RSI | < 30 (과매도) | 높음 — 반등 기대 |
| MACD | 히스토그램 양수 전환, 골든크로스 | 중간 — 모멘텀 전환 |
| MA | EMA12 > EMA26 (골든크로스), 가격 > SMA20 | 중간 — 추세 전환 |
| 볼린저 | %B < 0 (하단 이탈) | 중간 — 과매도 극단 |
| 고래 | 거래소 출금 다수 (outflow) | 높음 — 대형 매수자 축적 |

→ 이 중 **3개 이상 동시 매수 신호**면 BUY + 높은 confidence

### SELL 판단 기준
| 지표 | 매도 시그널 | 가중치(AI 재량) |
|------|-----------|---------------|
| RSI | > 70 (과매수) | 높음 — 조정 예상 |
| MACD | 히스토그램 음수 전환, 데드크로스 | 중간 — 모멘텀 약화 |
| MA | EMA12 < EMA26 (데드크로스), 가격 < SMA20 | 중간 — 하락 추세 |
| 볼린저 | %B > 1 (상단 돌파) | 중간 — 과매수 극단 |
| 고래 | 거래소 입금 다수 (inflow) | 높음 — 대형 매도 준비 |

→ 이 중 **3개 이상 동시 매도 신호**면 SELL + 높은 confidence

### HOLD 판단 기준
- 지표끼리 **상충** (RSI 매수인데 고래 매도 등)
- 대부분 **중립** 신호
- confidence가 낮아서 확신 부족

### Confidence Score (0~100)
AI가 자기 판단에 대한 확신도를 스스로 매김. 규칙:
```
90~100%  — 거의 모든 지표가 같은 방향 + 고래 데이터 확인
75~89%   — 3~4개 지표 일치 + 고래 약한 확인
60~74%   — 일부 지표 일치하나 상충도 있음
40~59%   — 혼재된 신호, 방향성 불확실
0~39%    — 데이터 부족하거나 판단 불가
```

**핵심: confidence가 높아도 자동매매 안 걸릴 수 있음.**
trading_params의 confidence_threshold(기본 70%) 이상이어야 실행됨.

### 실제 예시

**Strong Buy (confidence 85%):**
```
RSI 22 (oversold) ✅
MACD hist +4.5 (bullish) ✅
BB %B -0.15 (하단 이탈) ✅
Whale: outflow 4건 ✅
→ 4/4 컨플루언스 → BUY 85%
```

**Hold (confidence 65%):**
```
RSI 43 (neutral) —
MACD hist -1.96 (bearish) ⚠️
BB %B 0.24 (중립) —
Whale: 데이터 없음 —
→ 약세 편향이나 명확한 신호 없음 → HOLD 65%
```

### 사용자 파라미터가 AI에 미치는 영향

Parameters 탭에서 설정한 값이 AI 프롬프트에 **가이드라인**으로 전달됨:
```
- RSI 매수 임계값: 30 이하일 때 매수 고려 ← 사용자가 35로 바꾸면 AI도 35 기준으로 판단
- RSI 매도 임계값: 70 이상일 때 매도 고려
- 최대 매매 비율: 포트폴리오의 50%
- 지표 토글: MACD OFF 하면 → "MACD 무시할 것"이라고 프롬프트에 명시
```

AI는 이걸 **참고**하지 강제는 아님. RSI 매수 임계값 30인데 RSI 32면 AI 재량으로 매수할 수도 있음 (다른 지표가 강하면).

### 자동매매 실행 플로우
```
monitor_loop (60초마다)
│
├─ 데이터 수집 (가격/지표/고래)
├─ [시뮬레이션 ON이면 오버라이드 적용]
├─ Claude API 호출 → JSON 응답 파싱
│
└─ 자동매매 체크:
   ├─ auto_trade_enabled? → NO → 스킵
   ├─ action == "hold"? → YES → 스킵
   ├─ confidence >= threshold? → NO → 스킵 (65% < 70% 같은 경우)
   └─ ALL YES → 실행!
       ├─ 매매 금액 = min(AI추천%, max_trade%) × Vault잔고
       ├─ BUY: Vault.executeBuy() → USDT→BNB 스왑
       ├─ SELL: Vault.executeSell() → BNB→USDT 스왑
       └─ TradeRegistry.recordTrade() → 온체인 기록 (reasoning 포함)
```

---

## 6. 시뮬레이션 데모 시나리오

### Strong Buy 트리거 방법
1. Simulation 탭 → "Strong Buy" 프리셋 클릭
2. 자동 세팅: RSI=22(oversold), MACD hist=+4.5(bullish), BB %B=-15%(lower_break), Whale=outflow
3. 시뮬레이션 ON + 즉시 적용
4. 다음 모니터 사이클 (최대 60초 대기)에서 AI가 오버라이드된 지표로 분석
5. 높은 확률로 BUY 신호 + confidence 80%+ → 자동매매 실행
6. Agent Log 탭에서 실시간으로 확인 가능

### Strong Sell 트리거 방법
1. "Strong Sell" 프리셋: RSI=82(overbought), MACD=-5(bearish), BB=120%(upper_break), Whale=sell_pressure
2. AI가 SELL 판단 → 자동매매 실행

### 프리셋 값 테이블
| Preset | RSI | MACD Hist | BB %B | Whale |
|--------|-----|-----------|-------|-------|
| Strong Buy | 22 | +4.5 | -15% | outflow (매수 신호) |
| Mild Buy | 35 | +1.2 | 20% | outflow |
| Neutral | 50 | 0 | 50% | neutral |
| Mild Sell | 65 | -1.5 | 85% | sell_pressure |
| Strong Sell | 82 | -5.0 | 120% | sell_pressure |

### 빠르게 매매 트리거 하려면
Parameters 탭에서:
- confidence_threshold를 50%로 낮추기
- monitor_interval을 10초로 줄이기
→ 시뮬레이션 프리셋 적용하면 거의 즉시 자동매매 실행

---

## 7. 환경변수 (.env)

| 변수 | 설명 | 필수 |
|------|------|------|
| `BSC_TESTNET_RPC` | BSC 테스트넷 RPC URL | O |
| `BSC_MAINNET_RPC` | BSC 메인넷 RPC (가격 읽기용) | O |
| `BSCSCAN_API_KEY` | BSCScan API 키 (고래 감지) | O |
| `AGENT_PRIVATE_KEY` | 에이전트 지갑 프라이빗 키 (0x 접두사) | O |
| `ANTHROPIC_API_KEY` | Claude API 키 | O |
| `PANCAKE_BNB_USDT_POOL` | PancakeSwap V3 풀 주소 | O |
| `VAULT_ADDRESS` | Vault 컨트랙트 주소 | O (배포 후) |
| `TRADE_REGISTRY_ADDRESS` | TradeRegistry 주소 | O (배포 후) |
| `MOCK_ROUTER_ADDRESS` | MockRouter 주소 | O (배포 후) |
| `MOCK_USDT_ADDRESS` | MockUSDT 주소 | O (배포 후) |
| `MOCK_BNB_ADDRESS` | MockBNB 주소 | O (배포 후) |
| `MONITOR_INTERVAL` | 모니터 주기 (초, 기본 60) | X |

---

## 8. 실행 방법

```bash
# 1. venv 활성화
source .venv/bin/activate

# 2. 환경변수 로드
set -a && source .env && set +a

# 3. 서버 실행
cd agent && python main.py
# → http://localhost:8000

# 포트 충돌 시
lsof -ti:8000 | xargs kill -9
```

### 컨트랙트 재배포 (필요 시)
```bash
set -a && source .env && set +a
cd contracts
forge script script/Deploy.s.sol --rpc-url $BSC_TESTNET_RPC --broadcast
# → 출력된 주소를 .env에 업데이트
```

### 테스트
```bash
cd contracts && forge test -vv   # 16개 테스트
```

---

## 9. 파일별 핵심 코드 위치

| 파일 | 핵심 함수/위치 | 설명 |
|------|---------------|------|
| `main.py` | `monitor_loop()` L70~ | 60초 메인 루프 |
| `main.py` | `trading_params` L33~ | 사용자 설정 파라미터 |
| `main.py` | `overrides` L47~ | 시뮬레이션 오버라이드 |
| `main.py` | `agent_logs` / `add_log()` L26~ | 에이전트 로그 링버퍼 |
| `ai_analyst.py` | `SYSTEM_PROMPT` L8~ | AI 시스템 프롬프트 (한국어) |
| `ai_analyst.py` | `analyze()` L33~ | Claude API 호출 |
| `indicators.py` | `calculate_all()` | RSI/MACD/MA/BB 계산 |
| `price_feed.py` | `get_current_price()` | PancakeSwap slot0 가격 |
| `price_feed.py` | `get_ohlcv()` | Binance 1H OHLCV (41일) |
| `bsc_onchain.py` | `EXCHANGE_WALLETS` | 바이낸스 핫월렛 목록 |
| `executor.py` | `execute_buy/sell()` | 온체인 스왑 실행 |
| `frontend/index.html` | `showTab()` L1146~ | 탭 전환 로직 |
| `frontend/index.html` | `applyPreset()` L1333~ | 시뮬레이션 프리셋 |
| `frontend/index.html` | `fetchNetwork()` L1500~ | 네트워크 상태 |

---

## 10. 알려진 제한사항

- **MockRouter**: 고정 환율 (1 BNB = 600 USDT). 프로덕션에서는 PancakeSwap V2/V3 Router로 교체
- **Binance API**: 무료, API 키 불필요. rate limit 넉넉함. 최대 1000개 캔들 (41.6일분 1시간봉)
- **BSCScan 무료 API**: 초당 5회 제한. 고래 감지가 바이낸스 핫월렛에 한정
- **에이전트 로그**: 메모리 기반 (최대 200개). 서버 재시작 시 초기화
- **MetaMask/Rabby**: BSC Testnet만 지원. 메인넷 전환 시 chainId/RPC 변경 필요
- **지갑 전환**: 새 지갑 연결 시 이전 지갑의 active_user가 덮어씌워짐 (동시 다중 사용자 미지원)

---

## 11. 발표 킬링 포인트

1. **"규칙 기반이 아닌 AI 종합 판단"** — RSI<30이면 무조건 사는 봇이 아니라, 여러 지표 + 온체인 고래 데이터를 Claude가 종합 분석해서 판단. 같은 RSI 32여도 고래 매도 압력이 있으면 매수 보류.

2. **"BSC 경제성"** — 60초마다 분석, 매매 시 온체인 기록까지. 이더리움이면 기록 한 건에 $5+. BSC는 $0.03. AI 에이전트가 자주 거래해야 의미가 있으므로 저가스 체인이 필수.

3. **"실시간 데모"** — Simulation 탭으로 지표를 조작해서 AI가 BUY/SELL 판단하는 걸 라이브로 보여줌. Agent Log에서 reasoning이 실시간으로 흘러가는 거 보여주면 임팩트.

4. **"온체인 투명성"** — 모든 매매가 TradeRegistry에 기록됨. AI의 판단 근거(reasoning)까지 온체인. 누구나 검증 가능.
