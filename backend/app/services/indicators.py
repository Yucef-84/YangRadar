from __future__ import annotations


def moving_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    rolling = 0.0
    for idx, value in enumerate(values):
        rolling += value
        if idx >= window:
            rolling -= values[idx - window]
        result.append(round(rolling / window, 2) if idx >= window - 1 else None)
    return result


def obv(closes: list[float], volumes: list[int]) -> list[int]:
    result: list[int] = []
    current = 0
    for idx, close in enumerate(closes):
        if idx == 0:
            result.append(0)
            continue
        if close > closes[idx - 1]:
            current += volumes[idx]
        elif close < closes[idx - 1]:
            current -= volumes[idx]
        result.append(current)
    return result


def rsi(closes: list[float], window: int = 14) -> list[float | None]:
    if not closes:
        return []

    gains = [0.0]
    losses = [0.0]
    for idx in range(1, len(closes)):
        change = closes[idx] - closes[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    result: list[float | None] = [None] * len(closes)
    if len(closes) <= window:
        return result

    avg_gain = sum(gains[1 : window + 1]) / window
    avg_loss = sum(losses[1 : window + 1]) / window
    result[window] = _rsi_value(avg_gain, avg_loss)

    for idx in range(window + 1, len(closes)):
        avg_gain = ((avg_gain * (window - 1)) + gains[idx]) / window
        avg_loss = ((avg_loss * (window - 1)) + losses[idx]) / window
        result[idx] = _rsi_value(avg_gain, avg_loss)

    return result


def sentiment_10(closes: list[float]) -> list[float | None]:
    result: list[float | None] = []
    for idx in range(len(closes)):
        if idx < 10:
            result.append(None)
            continue
        wins = 0
        for lookback in range(idx - 9, idx + 1):
            if closes[lookback] > closes[lookback - 1]:
                wins += 1
        result.append(round(wins * 10.0, 2))
    return result


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

