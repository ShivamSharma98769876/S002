import numpy as np
import pandas as pd

def rsi(series, length=9):
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    gain_ema = pd.Series(gain, index=series.index).ewm(alpha=1/length, adjust=False).mean()
    loss_ema = pd.Series(loss, index=series.index).ewm(alpha=1/length, adjust=False).mean()

    rs = gain_ema / loss_ema.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val

def ema(series, length=3):
    return series.ewm(span=length, adjust=False).mean()

def wma(series, length=6):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def compute_pvs(df, rsi_len=9, ema_len=3, wma_len=6):
    """
    df: DataFrame with columns: 'open','high','low','close','volume'
    Index: DatetimeIndex at desired timeframe (e.g. 5min, 15min, 30min, 1H)
    """
    out = df.copy()

    # 1) RSI(9) on close
    out["rsi"] = rsi(out["close"], length=rsi_len)

    # 2) Price Strength = EMA(3) of RSI
    out["price_strength"] = ema(out["rsi"], length=ema_len)

    # 3) Volume Strength = WMA(6) of RSI
    out["volume_strength"] = wma(out["rsi"], length=wma_len)

    # 4) Zone info
    out["zone"] = np.where(out["rsi"] >= 50, "BUY", "SELL")

    # 5) Cross helpers
    def crossed_from_above(a, b):
        prev_a = a.shift(1)
        prev_b = b.shift(1)
        return (prev_a > prev_b) & (a <= b)

    def crossed_from_below(a, b):
        prev_a = a.shift(1)
        prev_b = b.shift(1)
        return (prev_a < prev_b) & (a >= b)

    price_cross_down = crossed_from_above(out["price_strength"], out["rsi"])
    vol_cross_down   = crossed_from_above(out["volume_strength"], out["rsi"])
    price_cross_up   = crossed_from_below(out["price_strength"], out["rsi"])
    vol_cross_up     = crossed_from_below(out["volume_strength"], out["rsi"])

    out["buy_signal"]  = price_cross_down & vol_cross_down
    out["sell_signal"] = price_cross_up & vol_cross_up

    return out
