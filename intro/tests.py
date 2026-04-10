import json
import unittest
from types import SimpleNamespace

from otree.api import Bot, Submission
from . import *
from soft_grouping import (
    build_soft_group_matrix,
    group_matrix_from_participant_match_id,
    should_force_nt_for_remainder_group,
)


class PlayerBot(Bot):
    def play_round(self):
        # Consent
        yield Consent, dict(consent=True)

        # Instructions (no form)
        yield Instructions

        yield InstructionsVideo

        # Comprehension (SurveyJS; submit via hidden field)
        survey_payload = {
            "q1": "b",
            "q2": "d",
            "q3": "a",
            "q4": "c",
            "q5": "d",
        }
        yield Submission(
            comprehensionQuestions,
            dict(
                surveyResults=json.dumps(survey_payload),
                cqAttemptCount="2",
                cqWrongFirstTry="true",
            ),
            check_html=False,
        )
        assert self.player.attention_check_passed is True
        assert self.player.cq_attempt_count == 2
        assert self.player.cq_wrong_first_try is True

        # Self assessment
        yield selfAssessment, dict(self_assesment=5)


class IntroPageTests(unittest.TestCase):
    def test_instructions_video_defaults_to_visible(self):
        player = SimpleNamespace(session=SimpleNamespace(config={}))
        assert InstructionsVideo.is_displayed(player) is True

    def test_instructions_video_respects_toggle(self):
        player = SimpleNamespace(session=SimpleNamespace(config={"show_intro_video_page": False}))
        assert InstructionsVideo.is_displayed(player) is False


class StaticGroupingTests(unittest.TestCase):
    @staticmethod
    def _fake_player(player_id, match_id=None):
        participant_vars = {}
        if match_id is not None:
            participant_vars["intro_group_match_id"] = match_id
        return SimpleNamespace(
            id_in_subsession=player_id,
            participant=SimpleNamespace(vars=participant_vars),
        )

    def test_build_soft_group_matrix_allows_last_remainder_group(self):
        players = [self._fake_player(idx) for idx in range(1, 40)]
        matrix = build_soft_group_matrix(players, 6, planned_participant_count=39)
        assert [len(group) for group in matrix] == [6, 6, 6, 6, 6, 6, 3]

    def test_build_soft_group_matrix_handles_divisible_session(self):
        players = [self._fake_player(idx) for idx in range(1, 37)]
        matrix = build_soft_group_matrix(players, 6, planned_participant_count=36)
        assert [len(group) for group in matrix] == [6, 6, 6, 6, 6, 6]

    def test_build_soft_group_matrix_handles_single_player_session(self):
        matrix = build_soft_group_matrix([self._fake_player(1)], 6, planned_participant_count=1)
        assert [len(group) for group in matrix] == [1]

    def test_group_matrix_from_participant_match_id_reconstructs_intro_groups(self):
        players = [
            self._fake_player(1, 1),
            self._fake_player(2, 1),
            self._fake_player(3, 2),
            self._fake_player(4, 2),
            self._fake_player(5, 2),
        ]
        matrix = group_matrix_from_participant_match_id(players)
        assert [len(group) for group in matrix] == [2, 3]

    def test_small_remainder_can_force_noise_trader(self):
        cfg = {
            "soft_group_matching_enabled": True,
            "small_remainder_force_nt_below_size": 6,
        }
        assert should_force_nt_for_remainder_group(cfg, realized_group_size=3, preferred_size=6) is True
        assert should_force_nt_for_remainder_group(cfg, realized_group_size=6, preferred_size=6) is False

    def test_small_remainder_force_noise_trader_threshold_is_adjustable(self):
        cfg = {
            "soft_group_matching_enabled": True,
            "small_remainder_force_nt_below_size": 3,
        }
        assert should_force_nt_for_remainder_group(cfg, realized_group_size=2, preferred_size=6) is True
        assert should_force_nt_for_remainder_group(cfg, realized_group_size=3, preferred_size=6) is False
