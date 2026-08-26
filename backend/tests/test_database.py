from __future__ import annotations

import sqlite3
from unittest import TestCase
from unittest.mock import patch

from backend.app import database


def _stock(code: str) -> dict[str, str | int]:
    return {
        "code": code,
        "name": f"종목 {code}",
        "market": "KOSPI",
        "sector": "테스트",
        "listed_shares": 1000,
        "security_type": "STOCK",
    }


class StockSnapshotTests(TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            """
            create table stocks (
                code text primary key,
                name text not null,
                market text not null,
                sector text,
                listed_shares integer,
                security_type text not null default 'STOCK',
                updated_at text not null
            )
            """
        )
        self.connection.execute(
            "insert into stocks(code,name,market,sector,listed_shares,security_type,updated_at) values(?,?,?,?,?,?,?)",
            ("999999", "기존 종목", "KOSPI", "테스트", 1000, "STOCK", "old"),
        )
        self.connection.commit()
        self.connect_patch = patch.object(database, "connect", return_value=self.connection)
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.connection.close()

    def test_partial_snapshot_preserves_existing_stocks(self) -> None:
        database.upsert_stocks([_stock(str(index).zfill(6)) for index in range(3001)], "new", complete=False)
        row = self.connection.execute("select code from stocks where code='999999'").fetchone()
        self.assertIsNotNone(row)

    def test_complete_snapshot_can_remove_stale_stocks(self) -> None:
        database.upsert_stocks([_stock(str(index).zfill(6)) for index in range(3001)], "new", complete=True)
        row = self.connection.execute("select code from stocks where code='999999'").fetchone()
        self.assertIsNone(row)
