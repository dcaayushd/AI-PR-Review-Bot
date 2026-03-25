import unittest

from pr_review_bot.config import ReviewSettings, RoutingSettings
from pr_review_bot.diff_parser import FilePatch
from pr_review_bot.risk import assess_review_risk, route_review_settings


class RiskRoutingTests(unittest.TestCase):
    def test_assess_review_risk_marks_sensitive_changes_as_high(self) -> None:
        patches = [
            FilePatch(path="src/auth/token_service.py", old_path="src/auth/token_service.py"),
            FilePatch(path=".github/workflows/review.yml", old_path=".github/workflows/review.yml"),
        ]
        patches[0].hunks = []
        patches[1].hunks = []
        assessment = assess_review_risk(patches)

        self.assertEqual(assessment.level, "high")
        self.assertGreaterEqual(assessment.score, 7)
        self.assertTrue(any("security-sensitive" in reason for reason in assessment.reasons))

    def test_route_review_settings_uses_fallback_for_low_risk(self) -> None:
        base = ReviewSettings(model="gpt-5.4", fallback_model="gpt-5-mini", reasoning_effort="medium")
        routing = RoutingSettings()
        assessment = assess_review_risk([FilePatch(path="src/ui/button.py", old_path="src/ui/button.py")])

        routed = route_review_settings(base, routing, assessment)

        self.assertEqual(routed.model, "gpt-5-mini")
        self.assertEqual(routed.reasoning_effort, "low")


if __name__ == "__main__":
    unittest.main()
