import json
import unittest
from unittest.mock import patch

from otree.api import Bot, Submission

from . import *
from . import export
from .pages import _is_last_round_of_market, _market_number_for_round, _should_elicit_forecast


class PlayerBot(Bot):
    def play_round(self):
        num_days = max(1, int(self.session.config.get("num_days", C.DAYS_PER_MARKET) or C.DAYS_PER_MARKET))
        if _should_elicit_forecast(self.round_number, num_days):
            forecast_payload = dict(
                forecast_price_next_day=100 + self.round_number,
                forecast_confidence_next_day=3,
                forecast_survey_json=json.dumps(
                    {
                        "forecast_price_next_day": 100 + self.round_number,
                        "forecast_confidence_next_day": 3,
                    }
                ),
            )
            yield Submission(DayBreak, forecast_payload, check_html=False)
        else:
            yield DayBreak

        if _is_last_round_of_market(self.round_number) and _market_number_for_round(self.round_number) < C.NUM_MARKETS:
            yield MarketTransition

        if self.round_number == C.NUM_ROUNDS:
            assert self.participant.vars.get("payable_market") in range(1, C.NUM_MARKETS + 1)
            assert "payoff_for_trade" in self.participant.vars
            assert "cumulative_bonuses" in self.participant.vars


class ExportTests(unittest.TestCase):
    def test_custom_export_mbo_includes_is_simulated(self):
        session_uuid = "session-sim-1"
        mbo_rows = [
            dict(
                trading_session_uuid=session_uuid,
                event_seq=7,
                event_ts="2026-03-12T15:23:44+00:00",
                record_kind="order",
                event_type="add",
                side="bid",
                order_id="order-1",
                trader_uuid="trader-1",
                price=120.0,
                size=1.0,
                size_delta=1.0,
                size_resting_after=1.0,
                status_after="active",
                match_id="",
                contra_order_id="",
                bid_order_id="",
                ask_order_id="",
                bid_trader_uuid="",
                ask_trader_uuid="",
                event_json=json.dumps({"trading_day": 1, "queue_position": 1, "queue_size": 1}),
                created_ts=123.45,
            )
        ]
        with patch.object(export, "_market_number_by_session", return_value={session_uuid: 2}), patch.object(
            export, "_session_is_simulated_by_uuid", return_value={session_uuid: True}
        ), patch.object(export, "_fetch_persisted_mbo_rows", return_value=mbo_rows):
            rows = list(export.custom_export_mbo([]))

        assert rows[0][1] == "is_simulated"
        assert rows[1][0] == session_uuid
        assert rows[1][1] is True
        assert rows[1][2] == 2
        assert rows[1][3] == 1

    def test_custom_export_mbp1_includes_is_simulated(self):
        session_uuid = "session-sim-2"
        mbp1_rows = [
            dict(
                trading_session_uuid=session_uuid,
                event_seq=3,
                event_ts="2026-03-12T15:23:44+00:00",
                source_mbo_event_seq=7,
                source_order_id="order-1",
                source_event_type="add",
                best_bid_px=120.0,
                best_bid_sz=1.0,
                best_bid_ct=1,
                best_ask_px=130.0,
                best_ask_sz=1.0,
                best_ask_ct=1,
                spread=10.0,
                midpoint=125.0,
                created_ts=223.45,
            )
        ]
        mbo_rows = [
            dict(
                trading_session_uuid=session_uuid,
                event_seq=7,
                event_json=json.dumps({"trading_day": 2}),
            )
        ]
        with patch.object(export, "_market_number_by_session", return_value={session_uuid: 1}), patch.object(
            export, "_session_is_simulated_by_uuid", return_value={session_uuid: True}
        ), patch.object(export, "_fetch_persisted_mbp1_rows", return_value=mbp1_rows), patch.object(
            export, "_fetch_persisted_mbo_rows", return_value=mbo_rows
        ):
            rows = list(export.custom_export_mbp1([]))

        assert rows[0][1] == "is_simulated"
        assert rows[1][0] == session_uuid
        assert rows[1][1] is True
        assert rows[1][2] == 1
        assert rows[1][3] == 2
