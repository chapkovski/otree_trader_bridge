import json
from otree.api import Bot, Submission
from . import *


class PlayerBot(Bot):
    def play_round(self):
        # Consent
        yield Consent, dict(consent=True)

        # Instructions (no form)
        yield Instructions

        # Comprehension (SurveyJS; submit via hidden field)
        survey_payload = {
            "q1": "b",
            "q2": "d",
            "q3": "b",
            "q4": "c",
            "q5": "d",
        }
        yield Submission(
            comprehensionQuestions,
            dict(surveyResults=json.dumps(survey_payload)),
            check_html=False,
        )

        # Self assessment
        yield selfAssessment, dict(self_assesment=5)
