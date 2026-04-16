# AlphaSwap — How It Works

A detailed explanation of how AlphaSwap operates: how the AI makes trading decisions, how confidence scores and trade amounts are determined, and how the Vault contract manages user funds.

---

## 1. Overall Flow

When the server starts, a **main loop** (`monitor_loop`) runs every 60 seconds. Each cycle executes 5 stages sequentially.

```
┌──────────────────────────────────────────────────────────┐
│  1. Price Data Collection                                │
│     - PancakeSwap V3 slot0() → live BNB/USDT price       │
│     - Binance API → 41 days of 1H OHLCV + volume         │
│                                                          │
│  2. Technical Indicator Calculation (indicators.py)      │
│     - RSI(14), MACD(12/26/9), SMA(20/50/200)             │
│     - EMA(12/26), Bollinger Bands(20, 2σ)                │
│     - 24-hour cumulative volume                          │
│                                                          │
│  3. BSC On-chain Whale Data (bsc_onchain.py)             │
│     - Large BNB transfer detection via Binance hot       │
│       wallets                                            │
│     - Exchange inflow = sell pressure                    │
│     - Exchange outflow = buy signal                      │
│                                                          │
│  4. AI Analysis (ai_analyst.py)                          │
│     - All data sent as structured text to Claude         │
│     - Claude returns BUY / SELL / HOLD decision          │
│     - Confidence 0–100% + trade % + reasoning            │
│                                                          │
│  5. Auto-trade Execution (executor.py)                   │
│     - If confidence >= threshold (default 70%)           │
│     - Swap tokens via Vault contract on BSC Testnet      │
│     - Record trade + AI reasoning on-chain in            │
│       TradeRegistry                                      │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Price Data Collection

### 2-1. Current Price (PancakeSwap V3)

A read-only `slot0()` call to the PancakeSwap V3 BNB/USDT pool on BSC mainnet. Zero gas cost (view function).

```
Pool address: 0x36696169C63e42cd08ce11f5deeBbCeBae652050

slot0() → sqrtPriceX96 (uint160)

Price calculation:
  price = (sqrtPriceX96 / 2^96)^2
  → token1/token0 = USDT per BNB
  → if price < 1, invert (handles reversed token ordering)
```

### 2-2. OHLCV Candle Data (Binance)

Fetches 41 days of 1-hour candles from Binance's public API. No API key required.

```
GET https://api.binance.com/api/v3/klines
  ?symbol=BNBUSDT
  &interval=1h
  &limit=984        (= 41 days × 24 hours)

Returns per candle:
  [openTime, open, high, low, close, volume, closeTime, ...]

→ Converted to pandas DataFrame
→ Cast to float
→ 6 columns used: [timestamp, open, high, low, close, volume]
```

**Why 41 days?**
- SMA(200) requires at least 200 candles
- 41 days × 24 hours = 984 candles → sufficient for all indicators including SMA(200)
- Binance API returns up to 1000 candles per call (~41.6 days)

---

## 3. Technical Indicators

Computed in `indicators.py` using the pandas-ta library. All based on **1-hour candles**.

### RSI (14)
- Relative Strength Index over 14 hours.
- Range: 0–100
- < 30: **Oversold** → potential bounce → buy signal
- \> 70: **Overbought** → potential correction → sell signal
- 30–70: Neutral

### MACD (12/26/9)
- Moving Average Convergence Divergence
- MACD line = EMA(12) - EMA(26)
- Signal line = EMA(9) of MACD
- **Histogram** = MACD line - Signal line
  - Positive → bullish (upward momentum)
  - Negative → bearish (downward momentum)
  - Positive crossover = golden cross (buy), Negative crossover = death cross (sell)

### Moving Averages (MA)
- **SMA(20)**: 20-hour simple moving average — short-term trend
- **SMA(50)**: 50-hour — medium-term trend
- **SMA(200)**: 200-hour — long-term trend (calculable with 41 days of data)
- **EMA(12/26)**: Exponential moving averages — heavier weight on recent prices
- **Golden cross**: SMA(20) crosses above SMA(50) → bullish reversal signal
- **Death cross**: SMA(20) crosses below SMA(50) → bearish reversal signal
- **Price vs SMA(20)**: price above SMA(20) = "above" (uptrend)

### Bollinger Bands (20, 2σ)
- Middle band = SMA(20)
- Upper band = SMA(20) + 2 × standard deviation
- Lower band = SMA(20) - 2 × standard deviation
- **%B** = (current price - lower) / (upper - lower)
  - %B < 0: Lower band break → extreme oversold → buy signal
  - %B > 1: Upper band break → extreme overbought → sell signal
  - 0–1: Within bands (neutral)

### 24-Hour Volume
- Sum of the most recent 24 hourly candle volumes
- Passed to the AI as "BNB volume: N BNB"
- Higher-than-normal volume reinforces the current trend's strength

---

## 4. Whale Data (BSC On-chain)

`bsc_onchain.py` monitors large BNB transfers from Binance hot wallets via the BSCScan API.

```
Monitored addresses (EXCHANGE_WALLETS):
  - 6 Binance hot wallet addresses

Threshold: 200+ BNB per transfer

Direction:
  External → Exchange = inflow  → whale depositing to sell → sell pressure
  Exchange → External = outflow → whale withdrawing to hold → buy signal

Net flow:
  inflow > outflow → "sell_pressure"
  outflow > inflow → "buy_signal"
  equal            → "neutral"
```

**Why does whale data matter?**
Technical indicators only reflect past price patterns. Large whale transfers reveal **future trading intent not yet reflected in price**. When indicators are ambiguous, whale data helps the AI determine direction.

---

## 5. AI Analysis — Decision Criteria

### Prompt Structure Sent to Claude

```
[System Prompt]
  - Role: BNB/USDT trading AI analyst
  - Principles:
    1. Don't rely on a single indicator — confirm confluence
    2. Use whale data as a leading indicator of market sentiment
    3. If conviction is low, recommend hold
    4. Never exceed 50% of portfolio in a single trade
    5. Consider recent trade history — avoid repeated trades
       in the same direction
  - Response format: JSON

[User Prompt]
  - Current price: $597.67
  - RSI(14): 43.52 (neutral)
  - MACD: -3.15 / -1.19 / hist -1.96 (bearish)
  - SMA(20): 601.45, SMA(50): 598.2, SMA(200): 603.77
  - EMA(12): 599.1, EMA(26): 600.3, Cross: death_cross
  - Bollinger: 615.2 / 601.45 / 587.7, %B: 0.24
  - 24H Volume: 123,456 BNB
  - Whale: neutral, 0 inflows, 0 outflows
  - [User parameters: RSI thresholds, indicator toggles, max trade %]
  - [Recent trade history (if available)]
  - [Current portfolio balance (if available)]
```

### Key: This Is NOT Rule-based

There are **no** hardcoded rules like "buy when RSI < 30". All indicator values are passed as text to the AI, and the AI makes a **holistic judgment**.

Given the same RSI of 32:
- Whale outflow + MACD golden cross → **BUY 85%**
- Whale inflow + MACD death cross → **HOLD 40%** (defer the buy)

The AI evaluates **conflicts and confluence** across indicators to determine the action and confidence.

### Conditions Favoring a BUY Decision

| Indicator | Signal | Context |
|-----------|--------|---------|
| RSI < 30 | Oversold | High bounce potential, but verify with other indicators |
| MACD histogram turns positive | Momentum shift | Downtrend weakening, potential reversal |
| EMA golden cross | Trend reversal | Short-term MA crossing above medium-term MA |
| Price > SMA(20) | Short-term uptrend | Price trading above short-term average |
| BB %B < 0 | Lower band break | Extremely undervalued, mean reversion expected |
| Multiple whale outflows | Accumulation | Large holders withdrawing BNB = buy signal |

When **3–4 indicators simultaneously point the same direction** → BUY with high confidence.

### Conditions Favoring a SELL Decision

| Indicator | Signal | Context |
|-----------|--------|---------|
| RSI > 70 | Overbought | Correction likely |
| MACD histogram turns negative | Momentum decline | Uptrend weakening, potential reversal |
| EMA death cross | Downtrend | Short-term MA crossing below medium-term MA |
| Price < SMA(20) | Short-term downtrend | Price trading below short-term average |
| BB %B > 1 | Upper band break | Extremely overvalued, mean reversion expected |
| Multiple whale inflows | Distribution | Large holders depositing to exchange = sell pressure |

### HOLD Decision
- Indicators **conflict** (RSI says buy, whale data says sell)
- Most signals are **neutral**
- No clear directional conviction
- **The AI's default tendency is HOLD** — the system prompt explicitly states "if conviction is low, recommend hold"

---

## 6. Confidence Score

The AI **self-assigns** a confidence score for its decision. This is not a mathematical formula — the AI qualitatively assesses the degree of indicator alignment.

### Score Ranges

| Range | Meaning | When It Occurs |
|-------|---------|----------------|
| **90–100%** | Near-certain | All indicators (RSI/MACD/MA/BB/whale) aligned. Extreme oversold + whale accumulation |
| **75–89%** | High conviction | 3–4 indicators aligned + whale data weakly confirming. Most auto-trades trigger here |
| **60–74%** | Moderate conviction | Some indicators aligned but conflicts exist. Near the default threshold (70%) |
| **40–59%** | Low conviction | Mixed signals, unclear direction. Usually results in HOLD |
| **0–39%** | Insufficient data | Data unavailable or extremely conflicting signals |

### Examples

**Strong Buy (confidence 85%):**
```
RSI 22 (oversold)                    ✅ Buy signal
MACD hist +4.5 (bullish)             ✅ Buy signal
BB %B -0.15 (lower_break)            ✅ Buy signal
Whale: 4 outflows                    ✅ Buy signal
→ 4/4 indicators aligned → confidence 85%
```

**Moderate Sell (confidence 72%):**
```
RSI 75 (overbought)                  ✅ Sell signal
MACD hist -2.1 (bearish)             ✅ Sell signal
BB %B 0.85 (neutral, near upper)     ⚠️ Not yet broken
Whale: 2 inflows                     ✅ Sell (weak signal)
→ 3 sell + 1 ambiguous → confidence 72%
```

**Hold (confidence 55%):**
```
RSI 48 (neutral)                     — Neutral
MACD hist -0.5 (bearish, weak)       ⚠️ Weak sell
BB %B 0.45 (neutral)                 — Neutral
Whale: no data                       — Inconclusive
→ Mostly neutral, no direction → HOLD 55%
```

### Important: High Confidence Does Not Guarantee Execution

Auto-trade execution requires:
```
confidence >= confidence_threshold (default 70%)
```

Example: AI returns BUY at 65% → below 70% threshold → **not executed**.
Lower the threshold in the Parameters tab for more aggressive trading.

---

## 7. Trade Amount Calculation

The AI returns `amount_percent` (1–50) alongside the action. This represents **what % of the Vault balance to trade**.

### Calculation

```
AI recommended %: amount_percent (e.g., 40%)
User max limit:   max_trade_percent (default 50%)
Applied %:        min(amount_percent, max_trade_percent) / 100

BUY:
  trade amount = Vault USDT balance × applied %
  e.g., 10,000 USDT × 40% = 4,000 USDT → swap to BNB

SELL:
  trade amount = Vault BNB balance × applied %
  e.g., 5.0 BNB × 40% = 2.0 BNB → swap to USDT
```

### How the AI Determines the Percentage

The system prompt instructs: "never exceed 50% of portfolio in a single trade." The AI adjusts the percentage based on confidence:

| Confidence | Typical AI Recommendation | Rationale |
|------------|--------------------------|-----------|
| 85–100% | 30–50% | Strong conviction → larger position |
| 70–84% | 15–30% | Moderate conviction → medium position |
| 60–69% | 5–15% | Low conviction → small position |
| < 60% | 0% (HOLD) | Insufficient conviction → no trade |

### Triple Safety Net

1. **AI self-limit**: System prompt prohibits exceeding 50%
2. **Server-side clamping**: `min(ai_amount, max_trade_percent)`
3. **User setting**: Adjustable `max_trade_percent` in Parameters tab

Example: AI recommends 40%, but user sets max_trade_percent to 20% → 20% applied.

---

## 8. Auto-trade Execution Conditions

All conditions must be met for a trade to execute:

```
① auto_trade_enabled == True       (Parameters tab: ON)
② VAULT_ADDRESS exists in .env     (contracts deployed)
③ AI action == "buy" or "sell"     (hold = do nothing)
④ confidence >= threshold           (default 70%+)
⑤ Calculated trade amount > 0      (balance must exist)
```

If any condition fails → **skip**. Retry in 60 seconds.

---

## 9. How User Parameters Affect AI Decisions

Values set in the Parameters tab are passed to the AI prompt as **guidelines**.

| Parameter | Sent to AI Prompt As | Example |
|-----------|---------------------|---------|
| rsi_buy_threshold | "Consider buying at or below RSI {value}" | 30 → 35 shifts the AI's buy zone |
| rsi_sell_threshold | "Consider selling at or above RSI {value}" | 70 → 65 triggers earlier sell decisions |
| max_trade_percent | "Max trade size: {value}% of portfolio" | AI uses as reference; also clamped server-side |
| use_whale_data | "no (ignore)" | OFF → AI ignores whale data |
| use_bollinger | "no (ignore)" | OFF → AI ignores Bollinger Bands |
| use_macd | "no (ignore)" | OFF → AI ignores MACD |
| use_ma | "no (ignore)" | OFF → AI ignores moving averages |

**These are guidelines, not absolute rules.**
If RSI buy threshold is 30 and current RSI is 32, the AI may still buy if other indicators show strong confluence. Parameters shift the AI's **reference points**, not enforce rigid rules.

---

## 10. Vault Architecture and Wallet Connection

### What Is the Vault?

The Vault is a **smart contract on BSC** that acts as a ledger, tracking per-user balances.

```
┌──────────────────────────────────────────────────────────┐
│  Vault Contract (deployed on BSC Testnet)                │
│                                                          │
│  ┌─ quoteBalances (USDT ledger) ───────────────────────┐ │
│  │  0xAAA... (Wallet A)  →  5,000 USDT                 │ │
│  │  0xBBB... (Wallet B)  →  2,000 USDT                 │ │
│  │  0xCCC... (Wallet C)  →      0 USDT  ← no deposit   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ baseBalances (BNB ledger) ─────────────────────────┐ │
│  │  0xAAA... (Wallet A)  →  3.5 BNB                    │ │
│  │  0xBBB... (Wallet B)  →    0 BNB                    │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ authorized (trading permission) ───────────────────┐ │
│  │  0xAgent...  →  true  ← set once at deployment      │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### How Balances Are Created (Wallet Connection ≠ Balance)

```
① Connect Wallet
   Connect 0xAAA via MetaMask
   → Registers with server: "trade on behalf of this wallet" (set-user)
   → Vault balance is 0 at this point. Nothing happens yet.

② Mint Test USDT (testnet only)
   MockUSDT.mint(0xAAA, 10000e18)
   → 10,000 USDT created in 0xAAA's wallet
   → Still outside the Vault. Balance remains 0.

③ Deposit to Vault ← This is where Vault balance is created!
   0xAAA signs via MetaMask:
     1) MockUSDT.approve(VaultAddress, 5000e18)  ← "Allow Vault to use my USDT"
     2) Vault.deposit(5000e18)                    ← "Put 5,000 USDT into Vault"

   Inside Vault:
     quoteBalances[0xAAA] += 5,000

   → Balance now recorded in Vault!

④ AI Auto-trading (agent executes on behalf)
   Agent server signs with its own key:
     Vault.executeBuy(0xAAA, 2000e18)

   Inside Vault:
     quoteBalances[0xAAA] -= 2,000 USDT
     baseBalances[0xAAA]  += 3.33 BNB

   → Agent swaps within the Vault — no user signature needed.
```

### Who Signs What?

| Action | Signer | Why |
|--------|--------|-----|
| Mint USDT | User (MetaMask) | Create tokens in user's wallet |
| Approve | User (MetaMask) | "Allow Vault to spend my USDT" |
| Deposit | User (MetaMask) | Move funds into Vault |
| Withdraw | User (MetaMask) | Move funds out of Vault |
| executeBuy | Agent (server) | AI decision → auto-trade |
| executeSell | Agent (server) | AI decision → auto-trade |
| recordTrade | Agent (server) | Store trade + AI reasoning on-chain |

**Users only sign for deposits and withdrawals.**
**The agent handles all trading within the Vault.**

### Agent Authorization — "Set Once at Deployment"

```
Deploy.s.sol deployment script:
  vault.setAuthorized(agentAddress, true);
  registry.setAuthorized(agentAddress, true);
  ─────────────────────────────────────────
  These two lines grant the agent master trading permission.

  After this, the agent can call:
    executeBuy(anyUser, anyAmount)
    executeSell(anyUser, anyAmount)
    recordTrade(...)

  Whether Wallet A or Wallet B connects
  → the agent simply changes the user parameter
  → no additional authorization needed
```

### Wallet Switching Flow

```
[Current state: Wallet A connected]

  Server memory: active_user = 0xAAA
  AI trades → executeBuy(0xAAA, ...) → trades using A's Vault balance

[Switch to Wallet B]

  1. Switch account in MetaMask
  2. Frontend → POST /api/set-user { address: "0xBBB" }
  3. Server memory: active_user = 0xBBB  (overwritten)
  4. AI trades → executeBuy(0xBBB, ...) → trades using B's Vault balance

  ※ A's balance remains untouched in the Vault.
  ※ If B's Vault balance is 0, trade amount = 0 → auto-trade skipped.
```

### Step-by-Step Usage Guide

```
[Step 1] Connect Wallet
   Click "Connect Wallet" in the dashboard sidebar
   → MetaMask/Rabby popup → BSC Testnet auto-added → connected
   → active_user registered on server
   → At this point: Vault balance is 0. AI has nothing to trade.

[Step 2] Click "MINT 10,000 TEST USDT"
   → MetaMask signature popup (1 tx)
   → 10,000 test USDT created in your wallet (testnet only)
   → At this point: USDT in wallet, but still outside Vault.

[Step 3] Click "DEPOSIT 5,000 USDT → VAULT"
   → MetaMask signature popup (2 txs: approve + deposit)
   → 5,000 USDT moves from wallet → Vault
   → quoteBalances[yourAddress] = 5,000 recorded in Vault
   → From this point: AI can auto-trade with your 5,000 USDT!

[Step 4] Auto-trading begins (automatic)
   → Next 60-second cycle: AI analyzes market
   → BUY decision + confidence 70%+ → agent executes trade
   → Your Vault balance: USDT decreases, BNB increases
   → Visible in real-time on the dashboard
```

### Gas Fee Breakdown

| Action | Paid By | Approximate Cost |
|--------|---------|-----------------|
| Mint USDT | User (MetaMask) | ~0.00015 BNB |
| Approve + Deposit | User (MetaMask) | ~0.0003 BNB |
| Withdraw | User (MetaMask) | ~0.00015 BNB |
| executeBuy | Agent (server) | ~0.0004 BNB |
| executeSell | Agent (server) | ~0.0004 BNB |
| recordTrade | Agent (server) | ~0.0004 BNB |

**Users only pay gas for deposits and withdrawals.**
**All AI trading gas fees are covered by the agent.**

---

## 11. Simulation Mode

In the Simulation tab, you can manually override indicators. The AI analyzes **overridden values instead of real indicators**.

### Quick Presets

| Preset | RSI | MACD Hist | BB %B | Whale |
|--------|-----|-----------|-------|-------|
| Strong Buy | 22 | +4.5 | -15% | outflow (buy signal) |
| Mild Buy | 35 | +1.2 | 20% | outflow |
| Neutral | 50 | 0 | 50% | neutral |
| Mild Sell | 65 | -1.5 | 85% | sell_pressure |
| Strong Sell | 82 | -5.0 | 120% | sell_pressure |

### How It Works
1. Click a preset → `POST /api/overrides` → override values saved on server
2. Simulation ON → `enabled: true`
3. Next monitor cycle uses overridden values instead of real indicators
4. **Price remains real** — only indicators are overridden
5. AI analyzes overridden indicators → if auto-trade conditions are met, **real trades execute**

---

## 12. On-chain Trade Execution Details

### BUY (USDT → BNB)
```
1. executor.execute_buy(user, amount_wei)
2. Vault.executeBuy(user, usdtAmount) internally:
   a. Deduct from user's Vault USDT balance
   b. Call MockRouter.swapExactTokensForTokens()
   c. Swap USDT → BNB (amountOut = amountIn * 1e18 / rate)
   d. Credit BNB to user's Vault BNB balance
3. executor.record_trade() → TradeRegistry records:
   - who (user), what (BNB/USDT), side (buy), amounts, price,
     AI reasoning, confidence
```

### SELL (BNB → USDT)
```
1. executor.execute_sell(user, amount_wei)
2. Vault.executeSell(user, bnbAmount) internally:
   a. Deduct from user's Vault BNB balance
   b. Call MockRouter.swapExactTokensForTokens()
   c. Swap BNB → USDT (amountOut = amountIn * rate / 1e18)
   d. Credit USDT to user's Vault USDT balance
3. executor.record_trade() → TradeRegistry records on-chain
```

### MockRouter Exchange Rate
- Testnet uses a fixed rate: 1 BNB = 600 USDT
- Set via `setRate(600e18)`
- In production, swap to the real PancakeSwap Router (single address change)

### Transaction Execution
- Built with web3.py → signed with agent's private key → sent to BSC Testnet
- Nonce: `w3.eth.get_transaction_count(address, "pending")` — includes pending txs to avoid nonce collision
- Gas limit: 5,000,000 (generous buffer; actual usage ~300k–425k)
- Waits for transaction receipt to confirm success/failure

---

## 13. Cost Structure

| Item | Cost | Frequency |
|------|------|-----------|
| Claude API (AI analysis) | ~$0.01/call (Sonnet) | Every 60s |
| BSC Testnet gas | 0 (testnet) | Per trade |
| BSC Mainnet price read | 0 (view function) | Every 60s |
| Binance API | 0 (free) | Every 60s |
| BSCScan API | 0 (free) | Every 60s |

**Hourly Claude API cost: ~$0.60** (60 calls × $0.01)
**Daily: ~$14.40**

Increase `monitor_interval` in the Parameters tab (e.g., 300s) to reduce costs.

---

## 14. Summary — One Full Cycle (60 seconds)

```
[0s]   Read BNB/USDT price from PancakeSwap V3 slot0() ($597.67)
[1s]   Fetch 41 days of 1H candles (984 candles + volume) from Binance
[2s]   Calculate RSI/MACD/MA/Bollinger Bands with pandas-ta
[3s]   Detect whale transfers via BSCScan API
[4s]   If simulation ON, replace indicators with override values
[5s]   Call Claude API — send all data as structured text
[10s]  Receive Claude response:
         { action: "buy", confidence: 82, amount_percent: 30,
           reasoning: "RSI 28 oversold + 3 whale outflows..." }
[11s]  Check auto-trade conditions:
         auto_trade ON ✅, confidence 82 >= 70 ✅, action=buy ✅
[12s]  Calculate trade amount:
         min(30%, 50%) = 30%
         Vault USDT balance 10,000 × 30% = 3,000 USDT
[13s]  Send Vault.executeBuy(user, 3000e18) transaction
[16s]  Transaction confirmed (BSC 3s block time)
         3,000 USDT → 5.0 BNB (at rate 600 USDT/BNB)
[17s]  TradeRegistry.recordTrade() — AI reasoning stored on-chain
[20s]  Dashboard auto-updates — Trade Ledger, Vault balance, AI Signal
[60s]  Next cycle begins
```
