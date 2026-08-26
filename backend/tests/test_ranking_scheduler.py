from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock, patch

from backend.app import main


class AutoSchedulerTests(TestCase):
    target_date = "2026-08-25"

    def setUp(self) -> None:
        self.original_provider = main.provider
        self.original_service = main.ranking_service
        main._reset_auto_scheduler_state()

        self.provider = Mock()
        self.provider.status.return_value = {"configured": True}
        self.provider.check_investor_readiness.return_value = {
            "ready": True,
            "target_date": self.target_date,
            "checked": True,
            "ready_count": 2,
            "sample_count": 3,
        }
        self.service = Mock()
        self.service.start.return_value = {"started": True, "message": "started"}
        main.provider = self.provider
        main.ranking_service = self.service

    def tearDown(self) -> None:
        main.provider = self.original_provider
        main.ranking_service = self.original_service
        main._reset_auto_scheduler_state()

    def _now(self, hour: int, minute: int, *, day: int = 25) -> datetime:
        return datetime(2026, 8, day, hour, minute, tzinfo=main._KST)

    def _set_latest(self, value: str | None = None) -> Mock:
        latest = patch.object(main, "get_latest_investor_date", return_value=value)
        latest.start()
        self.addCleanup(latest.stop)
        return latest

    def _set_job(self, status: str = "idle") -> Mock:
        job = patch.object(main, "get_ranking_job", return_value={"status": status})
        job.start()
        self.addCleanup(job.stop)
        return job

    def test_before_cutoff_waits_until_1540_without_readiness_call(self) -> None:
        self._set_latest()
        self._set_job()

        state = main._auto_scheduler_tick(self._now(15, 39))

        self.assertEqual(state["state"], "waiting_time")
        self.assertEqual(state["next_check_at"], "2026-08-25T15:40:00+09:00")
        self.provider.check_investor_readiness.assert_not_called()
        self.service.start.assert_not_called()

    def test_two_exact_samples_start_full_collection_once(self) -> None:
        self._set_latest()
        self._set_job()

        state = main._auto_scheduler_tick(self._now(15, 40))
        main._auto_scheduler_tick(self._now(15, 41))

        self.assertEqual(state["state"], "running")
        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_failed_collection_can_retry_after_ten_minutes(self) -> None:
        self._set_latest()
        job = patch.object(
            main,
            "get_ranking_job",
            side_effect=[{"status": "idle"}, {"status": "idle"}, {"status": "failed"}],
        )
        job.start()
        self.addCleanup(job.stop)

        main._auto_scheduler_tick(self._now(15, 40))
        main._auto_scheduler_tick(self._now(15, 45))
        main._auto_scheduler_tick(self._now(15, 50))

        self.assertEqual(self.provider.check_investor_readiness.call_count, 2)
        self.assertEqual(self.service.start.call_count, 2)
        self.assertEqual(self.service.start.call_args_list[-1].args, (self.target_date,))

    def test_partial_saved_failed_job_retries_after_the_scheduled_wait(self) -> None:
        latest = patch.object(
            main,
            "get_latest_investor_date",
            side_effect=[None, self.target_date, self.target_date],
        )
        latest.start()
        self.addCleanup(latest.stop)
        job = patch.object(
            main,
            "get_ranking_job",
            side_effect=[
                {"status": "idle"},
                {"status": "failed", "target_date": self.target_date, "failed": 3400},
                {"status": "failed", "target_date": self.target_date, "failed": 3400},
            ],
        )
        job.start()
        self.addCleanup(job.stop)

        main._auto_scheduler_tick(self._now(15, 40))
        waiting = main._auto_scheduler_tick(self._now(15, 45))
        main._auto_scheduler_tick(self._now(15, 50))

        self.assertNotEqual(waiting["state"], "completed")
        self.assertEqual(self.provider.check_investor_readiness.call_count, 2)
        self.assertEqual(self.service.start.call_count, 2)

    def test_running_worker_tick_does_not_overwrite_state_with_error(self) -> None:
        self._set_latest()
        job = patch.object(main, "get_ranking_job", side_effect=[{"status": "idle"}, {"status": "running"}])
        job.start()
        self.addCleanup(job.stop)

        main._auto_scheduler_tick(self._now(15, 40))
        state = main._auto_scheduler_tick(self._now(15, 41))

        self.assertEqual(state["state"], "running")
        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_started_false_can_be_retried_after_the_scheduled_wait(self) -> None:
        self._set_latest()
        self._set_job()
        self.service.start.side_effect = [
            {"started": False, "message": "already running"},
            {"started": True, "message": "started"},
        ]

        main._auto_scheduler_tick(self._now(15, 40))
        main._auto_scheduler_tick(self._now(15, 49))
        main._auto_scheduler_tick(self._now(15, 50))

        self.assertEqual(self.provider.check_investor_readiness.call_count, 2)
        self.assertEqual(self.service.start.call_count, 2)

    def test_saved_today_data_prevents_restart_after_previous_failure(self) -> None:
        latest = patch.object(main, "get_latest_investor_date", side_effect=[None, self.target_date])
        latest.start()
        self.addCleanup(latest.stop)
        self._set_job("failed")

        main._auto_scheduler_tick(self._now(15, 40))
        state = main._auto_scheduler_tick(self._now(15, 45))

        self.assertEqual(state["state"], "completed")
        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_partial_saved_today_job_is_resumed_after_the_next_check(self) -> None:
        latest = patch.object(main, "get_latest_investor_date", return_value=self.target_date)
        latest.start()
        self.addCleanup(latest.stop)
        job = patch.object(
            main,
            "get_ranking_job",
            return_value={
                "target_date": self.target_date,
                "status": "completed",
                "total": 3900,
                "saved": 500,
                "failed": 3400,
            },
        )
        job.start()
        self.addCleanup(job.stop)

        state = main._auto_scheduler_tick(self._now(15, 40))

        self.assertNotEqual(state["state"], "completed")
        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_completed_today_job_with_all_rows_skips_restart(self) -> None:
        latest = patch.object(main, "get_latest_investor_date", return_value=self.target_date)
        latest.start()
        self.addCleanup(latest.stop)
        job = patch.object(
            main,
            "get_ranking_job",
            return_value={
                "target_date": self.target_date,
                "status": "completed",
                "total": 3900,
                "saved": 3900,
                "failed": 0,
            },
        )
        job.start()
        self.addCleanup(job.stop)

        state = main._auto_scheduler_tick(self._now(15, 40))

        self.assertEqual(state["state"], "completed")
        self.provider.check_investor_readiness.assert_not_called()
        self.service.start.assert_not_called()

    def test_not_ready_waits_ten_minutes_before_retry(self) -> None:
        self._set_latest()
        self._set_job()
        self.provider.check_investor_readiness.return_value = {
            "ready": False,
            "target_date": self.target_date,
            "checked": True,
            "ready_count": 1,
            "sample_count": 3,
        }

        first = main._auto_scheduler_tick(self._now(15, 40))
        second = main._auto_scheduler_tick(self._now(15, 45))
        second_snapshot = main._auto_scheduler_snapshot()
        third = main._auto_scheduler_tick(self._now(15, 50))

        self.assertEqual(first["state"], "waiting_data")
        self.assertEqual(first["next_check_at"], "2026-08-25T15:50:00+09:00")
        self.assertEqual(second, second_snapshot)
        self.assertEqual(self.provider.check_investor_readiness.call_count, 2)
        self.service.start.assert_not_called()
        self.assertEqual(third["state"], "waiting_data")

    def test_readiness_error_never_starts_full_collection(self) -> None:
        self._set_latest()
        self._set_job()
        self.provider.check_investor_readiness.side_effect = RuntimeError("temporary")

        state = main._auto_scheduler_tick(self._now(15, 40))

        self.assertEqual(state["state"], "error")
        self.assertEqual(state["next_check_at"], "2026-08-25T15:50:00+09:00")
        self.service.start.assert_not_called()

    def test_all_readiness_sample_errors_are_reported_as_error(self) -> None:
        self._set_latest()
        self._set_job()
        self.provider.check_investor_readiness.return_value = {
            "ready": False,
            "status": "error",
            "target_date": self.target_date,
            "checked": True,
            "ready_count": 0,
            "sample_count": 3,
            "error_count": 3,
        }

        state = main._auto_scheduler_tick(self._now(15, 40))

        self.assertEqual(state["state"], "error")
        self.service.start.assert_not_called()

    def test_weekend_does_not_probe_or_start(self) -> None:
        self._set_latest()
        self._set_job()

        state = main._auto_scheduler_tick(self._now(15, 40, day=29))  # Saturday

        self.assertEqual(state["state"], "weekend")
        self.assertEqual(state["next_check_at"], "2026-08-31T15:40:00+09:00")
        self.provider.check_investor_readiness.assert_not_called()
        self.service.start.assert_not_called()

    def test_latest_today_skips_readiness_and_start(self) -> None:
        self._set_latest(self.target_date)
        self._set_job()

        state = main._auto_scheduler_tick(self._now(17, 0))

        self.assertEqual(state["state"], "completed")
        self.provider.check_investor_readiness.assert_not_called()
        self.service.start.assert_not_called()

    def test_existing_running_job_skips_readiness_and_start(self) -> None:
        self._set_latest()
        self._set_job("running")

        state = main._auto_scheduler_tick(self._now(17, 0))

        self.assertEqual(state["state"], "running")
        self.provider.check_investor_readiness.assert_not_called()
        self.service.start.assert_not_called()

    def test_app_started_after_cutoff_probes_immediately(self) -> None:
        self._set_latest()
        self._set_job()

        main._auto_scheduler_tick(self._now(17, 0))

        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_host_timezone_does_not_change_kst_cutoff(self) -> None:
        self._set_latest()
        self._set_job()
        utc_1540 = datetime(2026, 8, 25, 6, 40, tzinfo=timezone.utc)

        main._auto_scheduler_tick(utc_1540)

        self.provider.check_investor_readiness.assert_called_once_with(self.target_date)
        self.service.start.assert_called_once_with(self.target_date)

    def test_status_endpoint_exposes_scheduler_snapshot(self) -> None:
        self._set_latest()
        self._set_job()
        main._auto_scheduler_tick(self._now(15, 39))
        with patch.object(main, "get_investor_dates", return_value=[]):
            status = main.investor_ranking_status()

        self.assertIn("auto_scheduler", status)
        self.assertEqual(status["auto_scheduler"]["state"], "waiting_time")
        self.assertEqual(status["auto_scheduler"]["target_date"], self.target_date)
        self.assertEqual(status["auto_scheduler"]["next_check_at"], "2026-08-25T15:40:00+09:00")
