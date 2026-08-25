from __future__ import annotations

from datetime import datetime
from threading import Lock, Thread
from typing import Any

from ..database import save_investor_daily, save_ranking_job
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
            save_ranking_job(
                status="running",
                total=total,
                message=f"전체 {total:,}개 종목의 일별 수급을 수집하는 중입니다.",
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )

            last_saved_progress = {"completed": 0, "saved": 0, "failed": 0}

            def progress(completed: int, total_count: int, saved: int, failed: int) -> None:
                if completed == total_count or completed - last_saved_progress["completed"] >= 25:
                    last_saved_progress.update(completed=completed, saved=saved, failed=failed)
                    save_ranking_job(
                        status="running",
                        total=total_count,
                        completed=completed,
                        saved=saved,
                        failed=failed,
                        message=f"수급 수집 중 {completed:,}/{total_count:,}",
                        updated_at=datetime.now().isoformat(timespec="seconds"),
                    )

            rows, quality = self.provider.collect_investor_daily(stocks, target_date, progress)
            saved = save_investor_daily(rows, datetime.now().isoformat(timespec="seconds"))
            actual_dates = sorted({str(row["trade_date"]) for row in rows})
            message = quality.get("message") or f"{saved:,}개 종목 수급 수집 완료"
            if actual_dates:
                message += f" 기준일: {actual_dates[-1]}"
            status = "completed" if quality.get("status") in {"ok", "partial"} else "failed"
            save_ranking_job(
                status=status,
                total=total,
                completed=total,
                saved=saved,
                failed=max(total - saved, 0),
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
