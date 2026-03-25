import unittest

from pr_review_bot.llm_client import LLMClient, OutputProfile


class FakeAPIStatusError(Exception):
    pass


class LLMClientTests(unittest.TestCase):
    def test_extract_unsupported_param_finds_parameter_name(self) -> None:
        exc = FakeAPIStatusError(
            "Error code: 400 - {'error': {'message': \"Unsupported parameter: 'temperature' is not supported with this model.\"}}"
        )
        param = LLMClient._extract_unsupported_param(exc)  # type: ignore[arg-type]
        self.assertEqual(param, "temperature")

    def test_extract_unsupported_param_returns_none_when_absent(self) -> None:
        exc = FakeAPIStatusError("Something else went wrong")
        param = LLMClient._extract_unsupported_param(exc)  # type: ignore[arg-type]
        self.assertIsNone(param)

    def test_is_length_error_detects_length_limit_text(self) -> None:
        exc = Exception("Could not parse response content as the length limit was reached")
        self.assertTrue(LLMClient._is_length_error(exc))

    def test_output_profiles_include_compact_mode(self) -> None:
        client = object.__new__(LLMClient)
        client._settings = type(
            "Settings",
            (),
            {"max_issues": 18, "max_inline_comments": 8},
        )()
        profiles = LLMClient._output_profiles(client)
        self.assertEqual(
            profiles,
            [
                OutputProfile(name="default", max_findings=8, max_inline_comments=4, compact_mode=False),
                OutputProfile(name="compact", max_findings=4, max_inline_comments=2, compact_mode=True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
