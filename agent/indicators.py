import pandas as pd
import pandas_ta as ta


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> dict:
    """RSI (14-period on 1h candles = 14 hours)."""
    rsi = ta.rsi(df["close"], length=period)
    current = float(rsi.iloc[-1]) if rsi is not None and not rsi.empty else None

    signal = "neutral"
    if current is not None:
        if current < 30:
            signal = "oversold"
        elif current > 70:
            signal = "overbought"

    return {"value": round(current, 2) if current else None, "signal": signal, "period": period}


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD (12/26/9 on 1h candles)."""
    macd_df = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
    if macd_df is None or macd_df.empty:
        return {"macd": None, "signal_line": None, "histogram": None, "signal": "neutral"}

    macd_val = float(macd_df.iloc[-1, 0])
    signal_val = float(macd_df.iloc[-1, 1])
    hist_val = float(macd_df.iloc[-1, 2])

    if hist_val > 0:
        sig = "bullish"
    elif hist_val < 0:
        sig = "bearish"
    else:
        sig = "neutral"

    return {
        "macd": round(macd_val, 4),
        "signal_line": round(signal_val, 4),
        "histogram": round(hist_val, 4),
        "signal": sig,
    }


def calculate_ma(df: pd.DataFrame) -> dict:
    """Moving averages: SMA(20,50,200), EMA(12,26). Golden/Dead cross detection."""
    close = df["close"]

    sma20 = ta.sma(close, length=20)
    sma50 = ta.sma(close, length=50)
    sma200 = ta.sma(close, length=200)
    ema12 = ta.ema(close, length=12)
    ema26 = ta.ema(close, length=26)

    current_price = float(close.iloc[-1])

    def last_val(s):
        return round(float(s.iloc[-1]), 2) if s is not None and not s.empty and pd.notna(s.iloc[-1]) else None

    sma20_v = last_val(sma20)
    sma50_v = last_val(sma50)

    # Golden cross: SMA20 > SMA50 (and wasn't before)
    cross = "neutral"
    if sma20 is not None and sma50 is not None and len(sma20) > 1 and len(sma50) > 1:
        if pd.notna(sma20.iloc[-1]) and pd.notna(sma50.iloc[-1]):
            if pd.notna(sma20.iloc[-2]) and pd.notna(sma50.iloc[-2]):
                prev_above = float(sma20.iloc[-2]) > float(sma50.iloc[-2])
                curr_above = float(sma20.iloc[-1]) > float(sma50.iloc[-1])
                if curr_above and not prev_above:
                    cross = "golden_cross"
                elif not curr_above and prev_above:
                    cross = "dead_cross"

    return {
        "sma20": sma20_v,
        "sma50": sma50_v,
        "sma200": last_val(sma200),
        "ema12": last_val(ema12),
        "ema26": last_val(ema26),
        "price": round(current_price, 2),
        "cross": cross,
        "price_vs_sma20": "above" if sma20_v and current_price > sma20_v else "below",
    }


def calculate_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict:
    """Bollinger Bands (20-period, 2 std on 1h candles)."""
    bbands = ta.bbands(df["close"], length=period, std=std)
    if bbands is None or bbands.empty:
        return {"upper": None, "middle": None, "lower": None, "pct_b": None, "signal": "neutral"}

    # pandas-ta bbands column order: BBL, BBM, BBU, BBB, BBP
    lower = float(bbands.iloc[-1, 0])     # BBL
    middle = float(bbands.iloc[-1, 1])    # BBM
    upper = float(bbands.iloc[-1, 2])     # BBU
    bandwidth = float(bbands.iloc[-1, 3]) if bbands.shape[1] > 3 else None  # BBB
    pct_b = float(bbands.iloc[-1, 4]) if bbands.shape[1] > 4 else None      # BBP

    signal = "neutral"
    if pct_b is not None:
        if pct_b <= 0:
            signal = "lower_break"
        elif pct_b >= 1:
            signal = "upper_break"

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "bandwidth": round(bandwidth, 4) if bandwidth else None,
        "pct_b": round(pct_b, 4) if pct_b else None,
        "signal": signal,
    }


def calculate_all(df: pd.DataFrame) -> dict:
    """Calculate all indicators and return combined dict."""
    return {
        "rsi": calculate_rsi(df),
        "macd": calculate_macd(df),
        "ma": calculate_ma(df),
        "bollinger": calculate_bollinger(df),
    }
