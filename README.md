# AlphaSwap — AI Trading Agent on BSC

BSC 온체인 데이터 + 기술적 지표를 AI(Claude)가 종합 분석하여 PancakeSwap에서 자동 매매하는 DeFi 트레이딩 에이전트.

---

## How It Works

```
Every 60 seconds:

  PancakeSwap V3 slot0()  ──→  현재 BNB/USDT 가격
  CoinGecko OHLC API      ──→  7일치 1시간봉 캔들데이터
  BSCScan API              ──→  고래 BNB 대량 이체 감지
         │
         ▼
  ┌─────────────────────────────────┐
  │  Technical Indicators (1H)      │
  │  RSI(14) · MACD(12/26/9)       │
  │  SMA(20/50/200) · EMA(12/26)   │
  │  Bollinger Bands(20, 2σ)       │
  └─────────────┬───────────────────┘
                │
                ▼
  ┌─────────────────────────────────┐
  │  Claude AI Analysis             │
  │  지표 + 고래 데이터 종합 판단    │
  │  → BUY / SELL / HOLD           │
  │  → 신뢰도 0~100%               │
  │  → 한국어 판단 근거              │
  └─────────────┬───────────────────┘
                │
                ▼  confidence ≥ 70%
  ┌─────────────────────────────────┐
  │  BSC Testnet Auto-Swap          │
  │  Vault → MockRouter → 토큰교환  │
  │  TradeRegistry에 매매기록 저장   │
  └─────────────────────────────────┘
```

### AI 판단의 핵심 차별점

단순 규칙("RSI < 30이면 매수")이 아닌, **여러 지표 + 온체인 데이터를 AI가 종합 판단**:

> "RSI 32로 과매도 구간이지만, 고래 3건이 거래소에 대량 BNB를 입금 중이라 추가 하락 압력이 있습니다. 볼린저 하단 이탈 상태에서 MACD 히스토그램이 아직 음수 확대 중이므로 매수 시점을 늦추는 것이 안전합니다."

---

## Architecture

```
AlphaSwap/
├── contracts/                  # Solidity (Foundry)
│   ├── src/
│   │   ├── Vault.sol           # 사용자 예치/출금 + 에이전트 스왑 실행
│   │   ├── TradeRegistry.sol   # 매매 기록 온체인 저장
│   │   ├── MockRouter.sol      # PancakeSwap V2 Router 모킹
│   │   └── MockERC20.sol       # 테스트용 USDT, BNB 토큰
│   ├── test/AlphaSwap.t.sol    # 16개 테스트
│   └── script/Deploy.s.sol     # BSC Testnet 배포 스크립트
│
├── agent/                      # Python (FastAPI)
│   ├── main.py                 # FastAPI 서버 + 60초 모니터링 루프 + 시뮬레이션/로그/네트워크 API
│   ├── price_feed.py           # PancakeSwap slot0 현재가 + CoinGecko OHLCV
│   ├── indicators.py           # RSI, MACD, MA, Bollinger Bands 계산
│   ├── bsc_onchain.py          # BSCScan 고래 대량 이체 감지
│   ├── ai_analyst.py           # Claude API 종합 분석
│   ├── executor.py             # web3.py 스왑 실행 + 온체인 기록
│   └── config.py               # 환경변수 관리
│
├── frontend/
│   └── index.html              # 대시보드 4탭 (Sentinel/Parameters/Simulation/Agent Log)
│
└── abi/                        # 프론트엔드용 ABI + 컨트랙트 주소
```

---

## Smart Contracts

| Contract | Description |
|----------|-------------|
| **Vault.sol** | 사용자가 USDT 예치/출금. authorized agent만 `executeBuy()` / `executeSell()` 호출 가능. Router를 통해 토큰 스왑 실행. |
| **TradeRegistry.sol** | 매매 기록을 온체인에 저장. Trade 구조체에 user, pair, 매수/매도, 금액, 가격, AI 판단 근거, 신뢰도, 타임스탬프 포함. |
| **MockRouter.sol** | PancakeSwap V2 Router 인터페이스 모킹. owner가 `setRate()`로 교환비율 설정. 프로덕션 전환 시 주소만 교체. |
| **MockERC20.sol** | 테스트용 ERC20 토큰. `mint()` 자유 발행. USDT/BNB 역할. |

---

## Python Agent Modules

| Module | Description |
|--------|-------------|
| **price_feed.py** | PancakeSwap V3 BNB/USDT 풀 `slot0()`에서 현재가 읽기 (BSC 메인넷, 가스비 0). CoinGecko에서 7일 1시간봉 OHLCV. |
| **indicators.py** | pandas-ta로 기술적 지표 계산. RSI(14h), MACD(12/26/9h), SMA(20/50/200h), EMA(12/26h), Bollinger Bands(20h, 2σ). 골든크로스/데드크로스 판별. |
| **bsc_onchain.py** | BSCScan API로 고래 BNB 대량 이체 감지. 거래소 핫월렛 입금 = 매도 압력, 출금 = 매수 신호. |
| **ai_analyst.py** | Claude API에 기술 지표 + 고래 데이터 전달. JSON으로 action(buy/sell/hold), confidence, reasoning 반환. |
| **executor.py** | web3.py로 BSC 테스트넷 트랜잭션 전송. Vault 스왑 실행 + TradeRegistry 기록. |
| **main.py** | FastAPI 서버. 60초 모니터링 루프. 신뢰도 70%+ 시 자동 매매 실행. 파라미터/시뮬레이션/로그/네트워크 API. |

---

## Dashboard

실시간 대시보드 (http://localhost:8000) — 4개 탭 구성:

### Sentinel (메인 분석 화면)
- **캔들차트** — BNB/USDT 1시간봉 + SMA(20/50) + Bollinger Bands 오버레이
- **AI Signal 패널** — 매수/매도/홀드 배지 + 신뢰도 바 + 판단 근거
- **Indicator Grid** — RSI, MACD, MA, BB 각각의 값과 신호
- **Whale Tracker** — 고래 대량 이체 실시간 피드 (거래소 입출금 방향)
- **Sentiment Heatmap** — 4개 지표 불/베어 시각화
- **Trade Ledger** — 온체인 매매 기록
- **Force Buy/Sell** — 데모용 수동 매매 버튼

### Parameters (전략 설정)
- 자동매매 ON/OFF, 신뢰도 임계값, 최대 매매 비율
- RSI 매수/매도 임계값 설정 (시각적 존 바)
- 모니터 인터벌, 개별 지표 토글 (MACD/MA/BB/Whale)

### Simulation (데모 시뮬레이션)
- RSI/MACD/볼린저/고래 지표를 슬라이더로 수동 오버라이드
- Quick Preset 버튼 (Strong Buy / Mild Buy / Neutral / Mild Sell / Strong Sell)
- 오버라이드 ON 시 AI가 가짜 지표로 분석 → 자동매매 데모 가능

### Agent Log (실시간 에이전트 로그)
- 터미널 스타일 로그 뷰어 (가격, 지표, AI 판단, 매매 실행)
- 카테고리 필터 (AI / Trades / Indicators / Whale / Simulation)
- 10초 자동 새로고침 + auto-scroll

### 사이드바
- BSC Testnet 네트워크 상태 (블록 넘버, 가스비, 연결 상태)
- Vault 포트폴리오 잔고
- MetaMask 연결 — BSC Testnet 자동 추가

---

## Why BSC

1. **저가스 = AI 에이전트 경제성** — 60초마다 분석, 온체인 기록. BSC 가스비 $0.03/tx. 이더리움이면 $5+/tx.
2. **PancakeSwap 네이티브** — BSC 최대 DEX. BNB/USDT 유동성 최대.
3. **BSC 온체인 데이터 활용** — PancakeSwap slot0() 직접 읽기 + BSCScan 고래 감지.
4. **3초 블록 타임** — 매매 신호 → 3초 내 체결.

---

## Quick Start

### Prerequisites
- Python 3.13+
- Foundry (forge, cast)
- MetaMask
- BSC Testnet BNB ([Faucet](https://www.bnbchain.org/en/testnet-faucet))

### 1. Install

```bash
git clone https://github.com/your-repo/AlphaSwap.git
cd AlphaSwap

# Python dependencies
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r agent/requirements.txt

# Solidity dependencies
cd contracts
forge install
cd ..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — fill in API keys:
#   ANTHROPIC_API_KEY  (Claude AI analysis)
#   BSCSCAN_API_KEY    (whale detection)
#   AGENT_PRIVATE_KEY  (BSC testnet wallet)
```

### 3. Deploy Contracts

```bash
set -a && source .env && set +a
cd contracts
forge script script/Deploy.s.sol --rpc-url $BSC_TESTNET_RPC --broadcast
# Copy deployed addresses to .env
```

### 4. Run

```bash
source .venv/bin/activate
cd agent && python main.py
```

Open **http://localhost:8000**

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/api/status` | 현재가, 지표, AI 신호, 고래 데이터 |
| GET | `/api/ohlcv?days=7` | 캔들스틱 OHLCV 데이터 |
| GET | `/api/whales` | 고래 BNB 대량 이체 |
| GET | `/api/trades?count=20` | 온체인 매매 기록 |
| GET | `/api/portfolio/{address}` | Vault 잔고 |
| GET | `/api/logs?count=100` | 에이전트 활동 로그 |
| GET | `/api/network` | BSC Testnet 블록넘버, 가스비, 연결 상태 |
| GET | `/api/params` | 트레이딩 파라미터 조회 |
| POST | `/api/params` | 트레이딩 파라미터 변경 |
| GET | `/api/overrides` | 시뮬레이션 오버라이드 조회 |
| POST | `/api/overrides` | 시뮬레이션 오버라이드 설정 |
| POST | `/api/analyze` | 수동 분석 / Force Buy/Sell |

---

## Tech Stack

- **Smart Contracts**: Solidity 0.8.20, Foundry, OpenZeppelin
- **Backend**: Python 3.13, FastAPI, web3.py, pandas-ta
- **AI**: Anthropic Claude API (claude-sonnet-4-20250514)
- **Frontend**: TailwindCSS, lightweight-charts (TradingView)
- **Data**: PancakeSwap V3 slot0(), CoinGecko API, BSCScan API
- **Chain**: BSC Testnet (chainId: 97)

---

## Roadmap

- **Phase 1** (Hackathon MVP): BNB/USDT 단일 페어, 1시간봉 기술 지표 + 고래 감지, BSC 테스트넷
- **Phase 2**: PancakeSwap 풀 이벤트 파싱, 네트워크 가스 사용률, CAKE APR 등 온체인 데이터 확장
- **Phase 3**: 멀티 페어 지원, PancakeSwap V3 메인넷 연동, 백테스트 엔진
- **Phase 4**: ERC-4337 Paymaster 연동 (USDT로 가스비 대납)
- **Phase 5**: 전략 마켓플레이스 (복사 트레이딩) + 멀티체인 확장

---

## License

MIT
