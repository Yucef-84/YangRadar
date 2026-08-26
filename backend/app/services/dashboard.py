from __future__ import annotations

from typing import Any

from .indicators import moving_average, obv, rsi, sentiment_10


PERIODS = [5, 20, 60, 120]


def enrich_dashboard(raw: dict[str, Any], lookback: int) -> dict[str, Any]:
    ohlcv = raw.get("ohlcv", [])[-lookback:]
    stock = raw.get("stock", {})
    quote = raw.get("quote", {})
    listed_shares = int(stock.get("listed_shares") or 0)

    closes = [float(row["close"]) for row in ohlcv]
    volumes = [int(row["volume"]) for row in ohlcv]
    indicators = {
        "ma": {str(window): moving_average(closes, window) for window in [5, 10, 20, 60, 120]},
        "obv": obv(closes, volumes) if ohlcv else [],
        "rsi14": rsi(closes, 14) if ohlcv else [],
        "sentiment10": sentiment_10(closes) if ohlcv else [],
    }

    latest = ohlcv[-1] if ohlcv else {}
    previous = ohlcv[-2] if len(ohlcv) > 1 else latest
    close = quote.get("close") or latest.get("close")
    change = quote.get("change")
    if change is None and latest and previous:
        change = (latest.get("close", 0) or 0) - (previous.get("close", 0) or 0)
    change_rate = quote.get("change_rate")
    if change_rate is None and previous and previous.get("close"):
        change_rate = ((change or 0) / previous["close"]) * 100
    volume = quote.get("volume") or latest.get("volume")
    trading_value = quote.get("trading_value") or latest.get("trading_value")
    turnover = (volume / listed_shares * 100) if volume and listed_shares else None

    investors = raw.get("investors", [])[-lookback:]
    program_rows = raw.get("program_trading", [])[-lookback:]
    market_adr = raw.get("market_adr", [])[-lookback:]
    themes = raw.get("themes", [])

    return {
        "stock": stock,
        "summary": {
            "latest_date": latest.get("date"),
            "close": close,
            "change": change,
            "change_rate": round(change_rate, 2) if change_rate is not None else None,
            "volume": volume,
            "trading_value": trading_value,
            "turnover_rate": round(turnover, 4) if turnover is not None else None,
            "description": _description(stock, themes),
        },
        "ohlcv": ohlcv,
        "indicators": indicators,
        "investor_summary": _investor_summary(investors, listed_shares),
        "investors": investors[-40:],
        "program_summary": _program_summary(program_rows),
        "program_trading": program_rows[-40:],
        "market_adr": market_adr,
        "themes": themes,
        "timeframe": raw.get("timeframe", "daily"),
        "data_quality": raw.get("data_quality", {}),
    }


def _investor_summary(rows: list[dict[str, Any]], listed_shares: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for period in PERIODS:
        sliced = rows[-period:]
        foreign_qty = sum(int(row.get("foreign_qty") or 0) for row in sliced)
        institution_qty = sum(int(row.get("institution_qty") or 0) for row in sliced)
        result[str(period)] = {
            "foreign_qty": foreign_qty,
            "foreign_value": sum(float(row.get("foreign_value") or 0) for row in sliced),
            "foreign_ratio": _ratio(foreign_qty, listed_shares),
            "institution_qty": institution_qty,
            "institution_value": sum(float(row.get("institution_value") or 0) for row in sliced),
            "institution_ratio": _ratio(institution_qty, listed_shares),
            "days": len(sliced),
        }
    last5 = result["5"]
    return {
        "periods": result,
        "recent_outflow_5d": {
            "foreign_ratio": min(last5["foreign_ratio"], 0),
            "institution_ratio": min(last5["institution_ratio"], 0),
        },
    }


def _program_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for period in PERIODS:
        sliced = rows[-period:]
        result[str(period)] = {
            "net_amount_m": sum(float(row.get("net_amount_m") or 0) for row in sliced),
            "buy_amount_m": sum(float(row.get("buy_amount_m") or 0) for row in sliced),
            "sell_amount_m": sum(float(row.get("sell_amount_m") or 0) for row in sliced),
            "days": len(sliced),
        }
    return result


def _ratio(qty: float, listed_shares: int) -> float:
    if not listed_shares:
        return 0.0
    return round(qty / listed_shares * 100, 4)


def _description(stock: dict[str, Any], themes: list[dict[str, Any]]) -> str:
    market = _description_value(
        stock.get("market"),
        "상장시장 정보 없음",
        {"", "UNKNOWN", "N/A", "NA", "-", "시장정보없음", "상장시장정보없음"},
    )
    sector = _description_value(
        stock.get("sector"),
        "업종 정보 없음",
        {"", "UNKNOWN", "N/A", "NA", "-", "정보없음", "업종정보없음", "업종없음"},
    )
    theme_names: list[str] = []
    seen_names: set[str] = set()
    for theme in themes:
        raw_name = theme.get("name")
        name = str(raw_name).strip() if raw_name is not None else ""
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        theme_names.append(name)
        if len(theme_names) >= 3:
            break

    market_text = market if market == "상장시장 정보 없음" else f"{market} 상장 종목"
    sector_text = sector if sector == "업종 정보 없음" else f"업종 {sector}"
    parts = [market_text, sector_text]
    parts.append(f"키움 관련 테마: {', '.join(theme_names)}" if theme_names else "관련 테마 정보 없음")
    return " · ".join(parts) + "."


def _description_value(value: Any, fallback: str, missing_values: set[str]) -> str:
    text = str(value).strip() if value is not None else ""
    normalized = "".join(text.split()).upper()
    return fallback if normalized in missing_values else text
