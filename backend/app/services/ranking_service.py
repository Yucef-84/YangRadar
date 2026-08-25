from __future__ import annotations

from datetime import datetime
from threading import Lock, Thread
from typing import Any

from ..database import get_investor_codes, save_investor_daily, save_ranking_job
from .data_provider import DataProvider


class InvestorRankingService:
    """Runs the potentially long full-universe collection outside the request thread."""

    def __init__(self, provider: DataProvider):
        self.provider = provider
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self, target_date: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"started": False, "message": "이미 전체 수급 수집이 진행 중입니다."}
            date = target_date or datetime.now().date().isoformat()
            self._thread = Thread(target=self._run, args=(date,), daemon=True, name="yangradar-investor-ranking")
            self._thread.start()
        return {"started": True, "target_date": date, "message": "전체 종목 수급 수집을 시작했습니다."}

    def _run(self, target_date: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        save_ranking_job(
            status="running",
            target_date=target_date,
            total=0,
            completed=0,
            saved=0,
            failed=0,
            message="종목 목록을 가져오는 중입니다.",
            started_at=now,
            finished_at=None,
            updated_at=now,
        )
        try:
            stocks, stock_quality = self.provider.list_stocks()
            if not stocks:
                raise RuntimeError(stock_quality.get("message") or "수집할 종목이 없습니다.")

            from ..database import upsert_stocks

            upsert_stocks(stocks, datetime.now().isoformat(timespec="seconds"))
            total = len(stocks)
            existing_codes = get_investor_codes(target_date)
            pending_stocks = [stock for stock in stocks if str(stock.get("code") or "").zfill(6) not in existing_codes]
            already_saved = total - len(pending_stocks)
            save_ranking_job(
                status="running",
                total=total,
                completed=already_saved,
                saved=already_saved,
                failed=0,
                message=(
                    f"전체 {total:,}개 중 기존 성공 {already_saved:,}개를 건너뛰고 "
                    f"{len(pending_stocks):,}개를 수집하는 중입니다."
                ),
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )

            saved_total = {"count": already_saved}
            last_saved_progress = {"completed": already_saved, "saved": already_saved, "failed": 0}

            def save_batch(batch: list[dict[str, Any]]) -> None:
                saved_total["count"] += save_investor_daily(batch, datetime.now().isoformat(timespec="seconds"))
                save_ranking_job(
                    status="running",
                    total=total,
                    completed=last_saved_progress["completed"],
                    saved=saved_total["count"],
                    failed=last_saved_progress["failed"],
                    message=f"수급 수집 중 · 부분 저장 {saved_total['count']:,}개",
                    updated_at=datetime.now().isoformat(timespec="seconds"),
                )

            def progress(completed: int, total_count: int, saved: int, failed: int) -> None:
                full_completed = already_saved + completed
                if full_completed == total or full_completed - last_saved_progress["completed"] >= 25:
                    last_saved_progress.update(completed=full_completed, saved=saved_total["count"], failed=failed)
                    save_ranking_job(
                        status="running",
                        total=total,
                        completed=full_completed,
                        saved=saved_total["count"],
                        failed=failed,
                        message=f"수급 수집 중 {full_completed:,}/{total:,} · 부분 저장 {saved_total['count']:,}개",
                        updated_at=datetime.now().isoformat(timespec="seconds"),
                    )

            rows: list[dict[str, Any]] = []
            quality = {"status": "ok", "message": "기존 저장 데이터가 최신입니다."}
            if pending_stocks:
                rows, quality = self.provider.collect_investor_daily(
                    pending_stocks,
                    target_date,
                    progress,
                    save_batch,
                    include_values=False,
                    include_holdings=True,
                )
            saved = saved_total["count"]
            actual_dates = sorted({str(row["trade_date"]) for row in rows})
            message = quality.get("message") or f"{saved:,}개 종목 수급 수집 완료"
            if already_saved:
                message += f" 기존 성공 {already_saved:,}개 재사용"
            if actual_dates:
                message += f" 기준일: {actual_dates[-1]}"
            failed = max(total - saved, 0)
            status = "completed" if saved > 0 else "failed"
            save_ranking_job(
                status=status,
                total=total,
                completed=total,
                saved=saved,
                failed=failed,
                message=message,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )
        except Exception as exc:
            save_ranking_job(
                status="failed",
                message=str(exc),
                finished_at=datetime.now().isoformat(timespec="seconds"),
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )
