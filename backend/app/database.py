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
                security_type text not null default 'STOCK',
                updated_at text not null
            );

            create table if not exists dashboard_cache (
                code text primary key,
                payload_json text not null,
                updated_at text not null
            );

            create table if not exists investor_daily (
                trade_date text not null,
                code text not null,
                close real,
                listed_shares integer,
                market_cap real,
                foreign_net_qty real,
                foreign_net_value real,
                institution_net_qty real,
                institution_net_value real,
                foreign_change_ratio real,
                institution_change_ratio real,
                combined_change_ratio real,
                foreign_holding_qty real,
                foreign_holding_ratio real,
                data_status text not null default 'ok',
                updated_at text not null,
                primary key (trade_date, code)
            );

            create table if not exists ranking_jobs (
                id integer primary key check (id = 1),
                status text not null,
                target_date text,
                total integer not null default 0,
                completed integer not null default 0,
                saved integer not null default 0,
                failed integer not null default 0,
                message text,
                started_at text,
                finished_at text,
                updated_at text not null
            );
            """
        )
        columns = {row["name"] for row in conn.execute("pragma table_info(stocks)").fetchall()}
        if "security_type" not in columns:
            conn.execute("alter table stocks add column security_type text not null default 'STOCK'")
        conn.execute(
            """
            update ranking_jobs
            set status = 'failed',
                message = '이전 실행이 종료되어 수집이 완료되지 않았습니다. 다시 갱신하세요.',
                finished_at = coalesce(finished_at, updated_at)
            where status = 'running'
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
            select code, name, market, sector, listed_shares, security_type
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
            insert into stocks (code, name, market, sector, listed_shares, security_type, updated_at)
            values (:code, :name, :market, :sector, :listed_shares, :security_type, :updated_at)
            on conflict(code) do update set
                name = excluded.name,
                market = excluded.market,
                sector = excluded.sector,
                listed_shares = excluded.listed_shares,
                security_type = excluded.security_type,
                updated_at = excluded.updated_at
            """,
            [{"security_type": "STOCK", **stock, "updated_at": updated_at} for stock in stocks],
        )
        if len(stocks) > 3000:
            conn.execute("delete from stocks where updated_at <> ?", (updated_at,))


def search_cached_stocks(query: str, limit: int = 100) -> list[dict[str, Any]]:
    like = f"%{query}%"
    with connect() as conn:
        rows = conn.execute(
            """
            select code, name, market, sector, listed_shares, security_type
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


def save_investor_daily(rows: list[dict[str, Any]], updated_at: str) -> int:
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """
            insert into investor_daily (
                trade_date, code, close, listed_shares, market_cap,
                foreign_net_qty, foreign_net_value,
                institution_net_qty, institution_net_value,
                foreign_change_ratio, institution_change_ratio, combined_change_ratio,
                foreign_holding_qty, foreign_holding_ratio, data_status, updated_at
            ) values (
                :trade_date, :code, :close, :listed_shares, :market_cap,
                :foreign_net_qty, :foreign_net_value,
                :institution_net_qty, :institution_net_value,
                :foreign_change_ratio, :institution_change_ratio, :combined_change_ratio,
                :foreign_holding_qty, :foreign_holding_ratio, :data_status, :updated_at
            )
            on conflict(trade_date, code) do update set
                close = excluded.close,
                listed_shares = excluded.listed_shares,
                market_cap = excluded.market_cap,
                foreign_net_qty = excluded.foreign_net_qty,
                foreign_net_value = excluded.foreign_net_value,
                institution_net_qty = excluded.institution_net_qty,
                institution_net_value = excluded.institution_net_value,
                foreign_change_ratio = excluded.foreign_change_ratio,
                institution_change_ratio = excluded.institution_change_ratio,
                combined_change_ratio = excluded.combined_change_ratio,
                foreign_holding_qty = excluded.foreign_holding_qty,
                foreign_holding_ratio = excluded.foreign_holding_ratio,
                data_status = excluded.data_status,
                updated_at = excluded.updated_at
            """,
            [{**row, "updated_at": updated_at} for row in rows],
        )
    return len(rows)


def get_investor_dates(limit: int = 30) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "select distinct trade_date from investor_daily order by trade_date desc limit ?",
            (limit,),
        ).fetchall()
    return [str(row["trade_date"]) for row in rows]


def get_latest_investor_date() -> str | None:
    dates = get_investor_dates(1)
    return dates[0] if dates else None


def get_investor_ranking(
    trade_date: str,
    metric: str,
    direction: str,
    market: str,
    asset_type: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    metric_columns = {
        "foreign": "d.foreign_change_ratio",
        "institution": "d.institution_change_ratio",
        "combined": "d.combined_change_ratio",
    }
    if metric not in metric_columns:
        raise ValueError("unsupported metric")
    order = "asc" if direction == "outflow" else "desc"
    filters = ["d.trade_date = ?", "d.data_status = 'ok'", "s.security_type not in ('ETN', 'ELW')"]
    params: list[Any] = [trade_date]
    if market in {"KOSPI", "KOSDAQ"}:
        filters.append("s.market = ?")
        params.append(market)
    if asset_type == "ETF":
        filters.append("s.security_type = ?")
        params.append(asset_type)
    elif asset_type == "STOCK":
        filters.append("s.security_type <> 'ETF'")
    where = " and ".join(filters)
    score = metric_columns[metric]
    with connect() as conn:
        rows = conn.execute(
            f"""
            with current_ranked as (
                select
                    d.trade_date, d.code, s.name, s.market, s.security_type,
                    d.close, d.market_cap, d.listed_shares,
                    d.foreign_net_qty, d.foreign_net_value,
                    d.institution_net_qty, d.institution_net_value,
                    d.foreign_change_ratio, d.institution_change_ratio,
                    d.combined_change_ratio, d.foreign_holding_qty,
                    d.foreign_holding_ratio,
                    {score} as score,
                    row_number() over (order by {score} {order}, abs({score}) desc, d.code asc) as rank
                from investor_daily d
                join stocks s on s.code = d.code
                where {where}
            ), previous_ranked as (
                select d.code,
                    row_number() over (order by {score} {order}, abs({score}) desc, d.code asc) as rank
                from investor_daily d
                join stocks s on s.code = d.code
                where d.trade_date = (
                    select max(trade_date) from investor_daily where trade_date < ?
                )
                and d.data_status = 'ok'
                and s.security_type not in ('ETN', 'ELW')
                {"and s.market = ?" if market in {"KOSPI", "KOSDAQ"} else ""}
                {"and s.security_type = ?" if asset_type == "ETF" else "and s.security_type <> 'ETF'" if asset_type == "STOCK" else ""}
            )
            select current_ranked.*, previous_ranked.rank as previous_rank,
                   case when previous_ranked.rank is null then null
                        else previous_ranked.rank - current_ranked.rank end as rank_change
            from current_ranked
            left join previous_ranked on previous_ranked.code = current_ranked.code
            order by current_ranked.rank
            limit ?
            """,
            params + [trade_date] + params[1:] + [limit],
        ).fetchall()
    return [dict(row) for row in rows]


def get_ranking_job() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("select * from ranking_jobs where id = 1").fetchone()
    return dict(row) if row else {
        "id": 1,
        "status": "idle",
        "target_date": None,
        "total": 0,
        "completed": 0,
        "saved": 0,
        "failed": 0,
        "message": None,
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }


def save_ranking_job(**values: Any) -> None:
    defaults = get_ranking_job()
    payload = {**defaults, **values, "id": 1}
    with connect() as conn:
        conn.execute(
            """
            insert into ranking_jobs (
                id, status, target_date, total, completed, saved, failed,
                message, started_at, finished_at, updated_at
            ) values (
                :id, :status, :target_date, :total, :completed, :saved, :failed,
                :message, :started_at, :finished_at, :updated_at
            )
            on conflict(id) do update set
                status = excluded.status,
                target_date = excluded.target_date,
                total = excluded.total,
                completed = excluded.completed,
                saved = excluded.saved,
                failed = excluded.failed,
                message = excluded.message,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                updated_at = excluded.updated_at
            """,
            payload,
        )

