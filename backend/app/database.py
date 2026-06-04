from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "yangradar.sqlite3"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists stocks (
                code text primary key,
                name text not null,
                market text not null,
                sector text,
                listed_shares integer,
                updated_at text not null
            );

            create table if not exists dashboard_cache (
                code text primary key,
                payload_json text not null,
                updated_at text not null
            );
            """
        )


def get_cached_dashboard(code: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "select payload_json from dashboard_cache where code = ?",
            (code,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["payload_json"])


def get_cached_stock(code: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            select code, name, market, sector, listed_shares
            from stocks
            where code = ?
            """,
            (code,),
        ).fetchone()
    return dict(row) if row else None


def save_dashboard(code: str, payload: dict[str, Any], updated_at: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            insert into dashboard_cache (code, payload_json, updated_at)
            values (?, ?, ?)
            on conflict(code) do update set
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (code, json.dumps(payload, ensure_ascii=False), updated_at),
        )


def upsert_stocks(stocks: list[dict[str, Any]], updated_at: str) -> None:
    if not stocks:
        return
    with connect() as conn:
        conn.executemany(
            """
            insert into stocks (code, name, market, sector, listed_shares, updated_at)
            values (:code, :name, :market, :sector, :listed_shares, :updated_at)
            on conflict(code) do update set
                name = excluded.name,
                market = excluded.market,
                sector = excluded.sector,
                listed_shares = excluded.listed_shares,
                updated_at = excluded.updated_at
            """,
            [{**stock, "updated_at": updated_at} for stock in stocks],
        )
        if len(stocks) > 3000:
            conn.execute("delete from stocks where updated_at <> ?", (updated_at,))


def search_cached_stocks(query: str, limit: int = 100) -> list[dict[str, Any]]:
    like = f"%{query}%"
    with connect() as conn:
        rows = conn.execute(
            """
            select code, name, market, sector, listed_shares
            from stocks
            where name like ? or code like ?
            order by
                case
                    when code = ? then 0
                    when name = ? then 1
                    when name like ? then 2
                    when name like ? then 3
                    else 4
                end,
                case
                    when market in ('거래소', 'KOSPI', '코스피') then 0
                    when market in ('코스닥', 'KOSDAQ') then 1
                    when market in ('KONEX', '코넥스') then 2
                    when market like '%ETF%' then 8
                    when market like '%ETN%' then 9
                    else 4
                end,
                length(name),
                name
            limit ?
            """,
            (like, like, query, query, f"%{query}", f"{query}%", limit),
        ).fetchall()
    return [dict(row) for row in rows]

