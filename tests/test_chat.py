"""Chat plumbing: forecast routing and Postgres-backed history.

Needs a seeded database. Run `python -m backend.seed` first; otherwise the
Postgres-dependent tests skip.
"""

import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.exc import SQLAlchemyError

from backend import history
from backend.database import SessionLocal
from backend.models_db import ChatSession, User
from backend.sql_agent import forecast_frames


class ForecastRoutingTests(unittest.TestCase):
    def test_non_forecast_question_is_not_routed(self):
        self.assertIsNone(forecast_frames("Which carrier is slowest?"))

    def test_forecast_without_sku_is_not_routed(self):
        # No SKU means no series to project, so fall through to the SQL planner.
        self.assertIsNone(forecast_frames("Forecast demand for next quarter"))

    def test_forecast_frames_carry_table_chart_and_meta(self):
        try:
            frames = forecast_frames("Prediksi stok PAPER-0197 untuk 3 bulan")
        except SQLAlchemyError as error:
            raise unittest.SkipTest(f"Postgres unavailable: {error}")
        if frames is None:
            self.fail("forecast question was not routed")

        self.assertEqual(["table", "chart", "meta"], [f["type"] for f in frames])
        table, chart, meta = frames
        self.assertEqual(["period", "quantity", "kind"], table["columns"])
        self.assertEqual({"actual", "forecast"}, {row[2] for row in table["rows"]})
        self.assertEqual(3, sum(row[2] == "forecast" for row in table["rows"]))
        self.assertEqual("line", chart["chart"]["type"])
        self.assertEqual(len(table["rows"]), len(chart["chart"]["labels"]))
        self.assertEqual("PAPER-0197", meta["forecast"]["sku"])


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.db = SessionLocal()
            cls.user = cls.db.query(User).first()
        except SQLAlchemyError as error:
            raise unittest.SkipTest(f"Postgres unavailable: {error}")
        if cls.user is None:
            cls.user = User(
                username=f"test-{uuid.uuid4().hex[:8]}",
                hashed_password="x",
                role="user",
            )
            cls.db.add(cls.user)
            cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_roundtrip_and_cascade_delete(self):
        session_id = str(uuid.uuid4())
        self.db.add(ChatSession(session_id=session_id, user_id=self.user.id))
        self.db.commit()

        history.add_message(self.db, session_id, "user", "how many orders?")
        history.add_message(
            self.db,
            session_id,
            "assistant",
            "400 orders.",
            {"sql": "SELECT count(*) FROM orders"},
        )

        turns = history.get_history(self.db, session_id)
        self.assertEqual(["user", "assistant"], [turn["role"] for turn in turns])
        self.assertEqual("SELECT count(*) FROM orders", turns[1]["sql"])
        self.assertNotIn("sql", turns[0])

        # Deleting the session must take its messages with it.
        chat_session = (
            self.db.query(ChatSession)
            .filter(ChatSession.session_id == session_id)
            .first()
        )
        self.db.delete(chat_session)
        self.db.commit()
        self.assertEqual([], history.get_history(self.db, session_id))


if __name__ == "__main__":
    unittest.main()
