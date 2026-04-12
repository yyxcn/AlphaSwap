# BuidlHack 2026 — AI 기술적 분석 자동매매 에이전트 (AlphaSwap)

## 프로젝트 한 줄 요약
BSC 온체인 데이터 + 기술적 지표를 AI가 종합 분석하여 PancakeSwap에서 자동 매매하는 BSC 네이티브 DeFi 트레이딩 에이전트.

---

## 왜 BSC(L1)여야 하는가 — 덱/피칭에서 반드시 설명할 것

1. **저가스 = AI 에이전트 경제성**: 에이전트가 60초마다 판단하고 매매 기록을 온체인에 쓰는 구조. BSC 가스비 $0.03이니까 하루 1440건 기록해도 $43. 이더리움이면 하루 $7,000+. 이 서비스 모델은 저가스 체인이어야 성립함.
2. **PancakeSwap 네이티브**: BSC 최대 DEX이자 유동성 허브. BNB/USDT 풀 유동성이 가장 깊어서 슬리피지 최소.
3. **BSC 온체인 데이터 활용**: 일반 기술적 지표(RSI, MACD)만 쓰면 어느 체인이든 똑같음. PancakeSwap 풀에서 직접 가격을 읽고, BSCScan API로 고래 BNB 대량 이체를 감지해서 AI 판단에 함께 넣는 게 BSC 네이티브 차별점.
4. **3초 블록 타임**: 매매 신호 발생 → 3초 내 체결. 빠른 실행이 트레이딩 에이전트의 핵심.

---

## 핵심 사용자 플로우
1. 사용자가 지갑 연결 → USDT를 Vault에 예치
2. 페어 선택 (BNB/USDT) + 전략 설정 (지표 임계값 or 자연어 "저점에서 알아서 사줘")
3. Python 에이전트가 실시간 가격 수집 → RSI, MACD, 이동평균선, 볼린저밴드 등 지표 계산
4. AI(Claude API)가 지표 종합 분석 → 매수/매도/홀드 판단 + 근거 제공
5. 매수/매도 신호 시 BSC 테스트넷에서 자동 스왑 실행
6. 매매 기록 온체인 저장 + 대시보드에서 차트/수익률/AI 판단 이력 확인

---

## 기술 스택
- 스마트 컨트랙트: Solidity 0.8.20, **Foundry** (forge, cast, anvil)
- 백엔드: Python 3.11+, FastAPI, web3.py, pandas-ta (지표 계산)
- AI: Anthropic Claude API (claude-sonnet-4-20250514)
- 프론트엔드: React 18, ethers.js v6, TailwindCSS, lightweight-charts
- 가격 데이터: PancakeSwap V3 slot0() (현재가, BSC 메인넷 읽기 전용) + CoinGecko API (1시간봉 OHLCV)
- 체인: BSC Testnet (chainId: 97, RPC: https://data-seed-prebsc-1-s1.binance.org:8545/)
- OpenZeppelin Contracts (forge install)

---

## 스마트 컨트랙트 구조 (Foundry 프로젝트)

### 필요한 컨트랙트 4개

**1. Vault.sol**
- 사용자가 USDT(MockERC20) 예치/출금
- owner가 에이전트 주소를 authorized로 등록
- 에이전트만 호출 가능한 executeBuy(), executeSell() 함수
- executeBuy: Vault에서 USDT 꺼내서 Router로 스왑 → 받은 토큰 Vault에 보관
- executeSell: Vault의 토큰을 Router로 스왑 → 받은 USDT를 사용자 잔고에 추가
- PancakeSwap V2 Router 인터페이스 사용 (swapExactTokensForTokens)

**2. TradeRegistry.sol**
- 매매 기록을 온체인에 저장하는 컨트랙트
- Trade 구조체: user, pair, isBuy, amountIn, amountOut, price, aiReasoning(string), confidence(uint8), timestamp
- recordTrade()는 authorized agent만 호출 가능
- getRecentTrades(count), getUserTrades(user) 조회 함수
- TradeRecorded 이벤트 emit

**3. MockERC20.sol**
- 테스트용 ERC20 토큰 (USDT, BNB 역할)
- mint() 함수로 자유롭게 발행 가능 (테스트넷용)
- decimals 설정 가능

**4. MockRouter.sol**
- PancakeSwap Router를 흉내내는 데모용 라우터
- owner가 setRate(tokenA, tokenB, rate)로 교환 비율 설정
- swapExactTokensForTokens() 구현 — 유동성 풀 없이 설정된 비율로 토큰 교환
- 실제 PancakeSwap과 동일한 인터페이스 유지 (프로덕션 전환 시 주소만 교체)

### 배포 스크립트 (script/Deploy.s.sol)
1. MockERC20 두 개 배포 (MockUSDT, MockBNB)
2. MockRouter 배포 → BNB/USDT 비율 설정 (예: 1 BNB = 600 USDT)
3. Vault 배포 (MockUSDT 주소 전달)
4. TradeRegistry 배포
5. 에이전트 지갑 주소를 Vault, TradeRegistry에 authorized로 등록
6. 테스트용으로 deployer에게 MockUSDT, MockBNB 대량 mint
7. MockRouter에 MockUSDT, MockBNB 유동성 공급 (mint해서 넣기)

### 테스트 (test/)
- Vault: deposit, withdraw, executeBuy, executeSell, 권한 체크
- TradeRegistry: recordTrade, getRecentTrades, getUserTrades
- MockRouter: setRate, swapExactTokensForTokens 정상 동작

### Foundry 설정
- forge install OpenZeppelin/openzeppelin-contracts --no-git
- remappings.txt에 @openzeppelin/ 매핑
- foundry.toml에 BSC Testnet RPC, BSCScan API 키 설정
- 배포 후 forge verify-contract로 BSCScan verify

---

## Python 에이전트 구조

### 파일 구성 7개

**1. config.py**
- .env에서 환경변수 로드 (dotenv)
- BSC_TESTNET_RPC, ANTHROPIC_API_KEY, AGENT_PRIVATE_KEY
- BSC 메인넷 RPC (온체인 데이터 읽기 전용): https://bsc-dataseed.binance.org/
- 컨트랙트 주소들 (배포 후 채우기)
- 모니터링 간격 (기본 60초)

**2. price_feed.py**
- 현재가: PancakeSwap V3 BNB/USDT 풀 slot0()에서 직접 읽기 (BSC 메인넷 RPC call, 가스비 0)
- OHLCV: CoinGecko API에서 과거 7일치 1시간봉 데이터 가져오기
- pandas DataFrame으로 반환 (컬럼: timestamp, open, high, low, close, volume)

**3. bsc_onchain.py** ← BSC 특화 (MVP 라이트 버전)
- BSCScan API로 고래 BNB 대량 이체 감지 (API 호출 1번)
  - 최근 1시간 내 $100K 이상 BNB 이체 필터링
  - 거래소 핫월렛(Binance 등)으로 대량 입금 = 매도 압력 신호
  - 거래소에서 대량 출금 = 매수/홀드 신호
- 반환: dict (whale_transfers 리스트, net_flow 방향)
- (Phase 2 로드맵: PancakeSwap 풀 이벤트 파싱, 네트워크 가스 사용률, CAKE APR 등 추가 예정)

**4. indicators.py**
- 캔들 타임프레임: **1시간봉** 기준 (모든 지표 동일)
- pandas-ta 라이브러리 사용
- calculate_rsi(df, period=14): RSI 14기간 (= 최근 14시간)
- calculate_macd(df, fast=12, slow=26, signal=9): MACD 12/26시간, 시그널 9시간
- calculate_ma(df): 이동평균선 — SMA(20h), SMA(50h), SMA(200h), EMA(12h), EMA(26h). 골든크로스(단기 SMA가 장기 SMA 위로 돌파)/데드크로스(반대) 판별 포함
- calculate_bollinger(df, period=20, std=2): 볼린저밴드 20시간 기준, 표준편차 2. 상단/중간/하단 + %B 값 (0 이하=하단 이탈, 1 이상=상단 이탈)
- calculate_all(df): 위 지표 전부 계산해서 dict로 반환

**5. ai_analyst.py**
- Claude API 호출하여 매매 판단
- 프롬프트에 3종류 데이터를 포함:
  - (A) 기술적 지표 (1시간봉 기준): RSI(14), MACD(12/26/9), 이동평균선(SMA20/50/200, EMA12/26, 골든/데드크로스 여부), 볼린저밴드(%B, 밴드폭)
  - (B) BSC 온체인: 고래 BNB 대량 이체 방향 (거래소 입금=매도 압력 / 출금=매수 신호)
  - (C) 컨텍스트: 최근 매매 이력, 현재 포지션
- AI에게 JSON 형식으로 응답 요청:
  - action: "buy" | "sell" | "hold"
  - confidence: 0~100
  - amount_percent: 보유금의 몇 % 매매할지
  - reasoning: 한국어 판단 근거 (기술 지표 + 고래 데이터 근거 포함)
  - indicators_summary: 각 지표별 신호 요약
- 핵심 차별점: 단순 규칙(RSI<30이면 매수)이 아니라, AI가 여러 지표 + 온체인 데이터를 종합 판단. "RSI는 과매도지만 고래가 거래소에 대량 입금 중이라 아직 매수하기 이르다" 같은 복합 판단
- JSON 파싱 (```json 감싸진 경우 처리)

**6. executor.py**
- web3.py로 BSC 테스트넷 연결
- execute_buy(user, amountIn): Vault.executeBuy() 트랜잭션 전송
- execute_sell(user, amountIn): Vault.executeSell() 트랜잭션 전송
- record_trade(): TradeRegistry.recordTrade() 호출
- 트랜잭션 해시 반환

**7. main.py**
- FastAPI 서버 (프론트엔드 API 제공)
- 메인 모니터링 루프 (asyncio background task):
  - 매 60초마다: 가격 수집 → 지표 계산 → BSC 온체인 데이터 수집 → AI 판단 → 신호 있으면 스왑 실행
- API 엔드포인트:
  - GET /api/status — 현재 가격, 기술 지표값(1시간봉), 고래 데이터, AI 신호
  - GET /api/trades — 최근 매매 이력
  - POST /api/analyze — 수동 분석 트리거 (Force Buy/Sell용)
  - GET /api/portfolio/{address} — 사용자 포트폴리오
  - GET /api/whales — 최근 고래 BNB 대량 이체 목록
- CORS 허용 (프론트엔드 연동)

### requirements.txt
- fastapi, uvicorn, web3, anthropic, pandas, pandas-ta, python-dotenv, aiohttp

---

## 프론트엔드 구조 (React)

### 화면 구성 6개

**1. 실시간 차트 (PriceChart.jsx)**
- lightweight-charts 라이브러리 사용 (TradingView 오픈소스)
- BNB/USDT 캔들차트 (메인) + SMA(20), SMA(50), SMA(200) 이동평균선 오버레이 + 볼린저밴드(상단/중간/하단) 오버레이
- RSI 서브차트 (하단 1)
- MACD 서브차트 (하단 2)
- 매수/매도 포인트를 차트에 마커로 표시 (초록 화살표=매수, 빨간 화살표=매도)

**2. AI 신호 패널 (AISignal.jsx)**
- 현재 AI 판단: 매수 / 매도 / 홀드 (큰 배지, 색상으로 구분)
- 신뢰도 퍼센트
- AI 판단 근거 텍스트
- 각 지표별 신호: RSI(과매도/중립/과매수), MACD(강세/중립/약세), 이동평균(골든크로스/데드크로스/중립), 볼린저밴드(하단이탈/중립/상단이탈)
- 마지막 업데이트 시간

**3. BSC 온체인 패널 (OnchainData.jsx)**
- 고래 이동: 최근 BNB 대량 이체 리스트 (금액 + 거래소 입금/출금 방향)
- 전체 넷플로우 방향 표시 (거래소 순입금 = 매도 압력 빨강, 순출금 = 매수 신호 초록)
- (Phase 2 로드맵: PancakeSwap 풀 거래량, TVL, 네트워크 지표 등 추가 예정)

**4. 전략 설정 (StrategyConfig.jsx)**
- 지표별 임계값 슬라이더 (RSI 매수선 기본 30, 매도선 기본 70 등)
- 1회 매매 금액 설정
- 활성화/비활성화 토글

**5. 매매 이력 (TradeHistory.jsx)**
- 테이블: 시간, 매수/매도, 수량, 가격, 수익률, AI 판단 근거, BSCScan 링크
- 온체인 데이터(TradeRegistry)에서 읽어오기

**6. 포트폴리오 (Portfolio.jsx)**
- Vault 잔고 (USDT + 보유 토큰 가치)
- 총 수익률
- 승률 (이익 매매 / 전체 매매)
- 입금/출금 버튼

### 공통
- MetaMask 지갑 연결 (BSC Testnet)
- 다크 테마 기본
- 모바일 반응형
- 색상: 매수 초록(#22C55E), 매도 빨강(#EF4444), 홀드 노랑(#EAB308)

---

## 데모 전략

### 가격 데이터
- 현재가: PancakeSwap V3 BNB/USDT 풀 slot0()에서 직접 읽기 (BSC 메인넷, 가스비 0)
- OHLCV 봉 데이터: CoinGecko API에서 과거 7일치 1시간봉 (지표 계산용)
- 이 데이터로 RSI/MACD/MA/볼린저 계산하고 AI가 판단
- 차트에는 실제 BNB 가격이 표시됨

### 스왑 실행
- 실제 스왑은 BSC 테스트넷의 MockRouter에서 실행
- MockRouter의 가격 비율은 PancakeSwap slot0() 실시간 가격과 주기적 동기화
- 데모할 때: "현재가는 PancakeSwap에서 직접 읽고, 실행은 테스트넷에서 시연합니다"

### 데모 시나리오
1. 대시보드 보여줌 — 실시간 BNB/USDT 1시간봉 캔들차트 + 이동평균선 + 볼린저밴드 + RSI/MACD 서브차트
2. BSC 온체인 패널: "최근 1시간 고래 3건 거래소 출금 감지 → 매수 신호"
3. AI 패널: "RSI 32(과매도), SMA20 골든크로스, 볼린저 하단 터치, 고래 거래소 출금 → 매수 신호, 신뢰도 82%"
4. Force Buy 버튼으로 매수 실행 → BSCScan 테스트넷에서 트랜잭션 확인
5. 매매 이력 테이블에 기록 추가 (시간, 매수, 100 USDT → 0.167 BNB, AI 근거, BSCScan 링크)

### 데모용 편의 기능
- "Force Buy" / "Force Sell" 버튼 — 피칭 중 AI 신호를 기다릴 수 없으니 수동 트리거
- MockRouter 가격을 수동으로 바꿀 수 있는 admin 패널 (가격 변동 시뮬레이션)

---

## 환경변수 (.env)

```
BSC_TESTNET_RPC=https://data-seed-prebsc-1-s1.binance.org:8545/
BSC_MAINNET_RPC=https://bsc-dataseed.binance.org/
BSCSCAN_API_KEY=BSCScan_API_키
AGENT_PRIVATE_KEY=에이전트_지갑_프라이빗키
ANTHROPIC_API_KEY=클로드_API_키
COINGECKO_API_URL=https://api.coingecko.com/api/v3

# PancakeSwap V3 BNB/USDT 풀 주소 (BSC 메인넷, 읽기 전용)
PANCAKE_BNB_USDT_POOL=0x36696169C63e42cd08ce11f5deeBbCeBae652050

# 배포 후 채우기
VAULT_ADDRESS=
TRADE_REGISTRY_ADDRESS=
MOCK_ROUTER_ADDRESS=
MOCK_USDT_ADDRESS=
MOCK_BNB_ADDRESS=
```

---

## 빌드 순서 (이 순서대로 하나씩 진행)

### Step 1: Foundry 프로젝트 초기화 + 컨트랙트 작성
- forge init, OpenZeppelin 설치, remappings 설정
- MockERC20, MockRouter, Vault, TradeRegistry 작성
- forge test로 전체 테스트 통과 확인

### Step 2: BSC 테스트넷 배포
- Deploy.s.sol 스크립트 작성
- forge script으로 배포
- forge verify-contract로 BSCScan verify
- 배포된 주소를 .env에 기록

### Step 3: Python 에이전트 코어
- price_feed.py — PancakeSwap slot0() 현재가 읽기 + CoinGecko 1시간봉 OHLCV 수집 동작 확인
- bsc_onchain.py — BSCScan API로 고래 대량 이체 감지 테스트
- indicators.py — 1시간봉 데이터로 RSI/MACD/MA/볼린저 계산 테스트
- ai_analyst.py — Claude API 호출 → 기술 지표 + 고래 데이터 함께 넘겨서 매매 판단 JSON 반환 확인
- executor.py — 테스트넷에서 실제 스왑 실행 확인

### Step 4: Python FastAPI 서버
- main.py — API 엔드포인트 + 모니터링 루프
- /api/status, /api/trades, /api/analyze 동작 확인

### Step 5: React 프론트엔드
- 차트 (lightweight-charts) + 지표 오버레이
- AI 신호 패널 + 매매 이력 + 포트폴리오
- 지갑 연결 + 입금/출금
- FastAPI 연동

### Step 6: 통합 테스트 + 데모 준비
- 전체 플로우 테스트 (입금 → AI 분석 → 스왑 → 기록 → 대시보드 반영)
- Force Buy/Sell 버튼 동작 확인
- 데모 영상 촬영 (2~3분)

### Step 7: 제출 준비
- README.md 문서화
- 프로젝트 덱 (PPT/PDF)
- 트윗 (@BNBChain + #BNBHack)
- Ludium에 제출

---

## 제출 체크리스트 (BNB Hack 기준)

- [ ] BSC 테스트넷에 컨트랙트 배포 완료
- [ ] 최소 2건 이상 성공 트랜잭션 (스왑 실행)
- [ ] BSCScan에서 컨트랙트 verify
- [ ] GitHub 오픈소스 (합리적 커밋 히스토리)
- [ ] 데모 영상 (2~3분)
- [ ] 프로젝트 덱 (PPT/PDF)
- [ ] 트윗: @BNBChain + #BNBHack + 트랙명
- [ ] README.md (설치법, 실행법, 아키텍처)
- [ ] 로드맵 포함

---

## 로드맵 (덱에 포함)

- Phase 1 (해커톤 MVP): BNB/USDT 단일 페어, 1시간봉 기준 기술 지표 + BSCScan 고래 감지 + PancakeSwap slot0 현재가, BSC 테스트넷
- Phase 2: PancakeSwap 풀 이벤트 파싱, 네트워크 가스 사용률, CAKE APR 등 온체인 데이터 확장
- Phase 3: 멀티 페어 지원 (CAKE/USDT, ETH/USDT 등), PancakeSwap V3 메인넷 연동, 백테스트 엔진
- Phase 4: ERC-4337 Paymaster 연동 (USDT로 가스비 대납 → BNB 없이 사용)
- Phase 5: 전략 마켓플레이스 (수익률 좋은 유저 전략 복사 트레이딩) + 멀티체인 확장

---

## 주의사항

- API 키, 프라이빗 키 절대 GitHub에 올리지 말 것 → .env + .gitignore
- CoinGecko 무료 API는 분당 10~30회 제한 → 60초 간격 모니터링 권장
- MockRouter 가격은 CoinGecko 실시간 가격과 주기적으로 동기화
- **BSC 메인넷 RPC는 읽기 전용으로만 사용** — 온체인 데이터 수집용. 트랜잭션은 절대 메인넷에 보내지 않음. 모든 스왑 실행은 테스트넷에서만.
- BSCScan API는 메인넷용(api.bscscan.com)과 테스트넷용(api-testnet.bscscan.com) URL이 다름. 용도에 맞게 사용.
- 프론트엔드 컨트랙트 주소/ABI는 배포 후 업데이트
- 테스트 BNB는 https://www.bnbchain.org/en/testnet-faucet 에서 받기
- lightweight-charts는 CDN으로 로드 가능 (npm 설치 or script 태그)
