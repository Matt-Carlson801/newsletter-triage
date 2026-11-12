"""Offline checks for Stage 4 (GitHub Actions). Everything is made up; the
network, Gmail and Gemini are replaced with fakes, so nothing is read or sent.

Run from the project root with:  python -m unittest discover tests
"""

import contextlib
import io
import logging
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import main  # noqa: E402
from config import ConfigError, Credentials, running_in_ci  # noqa: E402
from fetch import FetchError, Newsletter  # noqa: E402
from send import SendError  # noqa: E402
from summarize import NewsletterSummary, Story  # noqa: E402

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "daily-digest.yml"

# Distinctive fake private strings. If any of them shows up in CI output, a test fails.
SECRET_SENDER = "Private Sender <private-sender@secret-example.com>"
SECRET_SUBJECT = "SECRET-SUBJECT-LINE"
SECRET_TITLE = "SECRET-STORY-TITLE"
SECRET_SENTENCE = "SECRET-STORY-SENTENCE"
SECRET_URL = "https://secret-example.com/secret-link"
SECRET_ADDRESS = "me-secret@secret-example.com"
SECRET_ERROR = "leaked-detail-from-the-network"
PRIVATE_STRINGS = [SECRET_SENDER, SECRET_SUBJECT, SECRET_TITLE, SECRET_SENTENCE,
                   SECRET_URL, SECRET_ADDRESS, SECRET_ERROR, "secret-example.com"]

CREDS = Credentials(address=SECRET_ADDRESS, app_password="fakepassword")
WHEN = datetime(2026, 11, 10, 11, 30, tzinfo=timezone.utc)


def fake_newsletter() -> Newsletter:
    return Newsletter(sender=SECRET_SENDER, subject=SECRET_SUBJECT, date=WHEN, body="x",
                      links=[], unsubscribe=None)


def fake_summary() -> NewsletterSummary:
    return NewsletterSummary(stories=[Story(SECRET_TITLE, SECRET_SENTENCE, SECRET_URL, "AI & Tech")])


def run_main(argv: list[str], env: dict[str, str], **patches) -> tuple[int, str]:
    """Run main.main() with fakes and return (exit code, everything printed).

    `patches` replaces names inside main.py. Sensible fakes are used for
    anything not given, so a test only spells out what it cares about.
    """
    fakes = {
        "load_credentials": mock.Mock(return_value=CREDS),
        "load_recipient": mock.Mock(return_value=SECRET_ADDRESS),
        "connect": mock.Mock(),
        "fetch_newsletters": mock.Mock(return_value=[fake_newsletter()]),
        "summarize_all": mock.Mock(return_value=[fake_summary()]),
        "append_to_log": mock.Mock(return_value=1),
        "send_digest": mock.Mock(),
    }
    fakes.update(patches)
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict("os.environ", env, clear=True), \
         contextlib.ExitStack() as stack, \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        for name, fake in fakes.items():
            stack.enter_context(mock.patch(f"main.{name}", fake))
        code = main.main(argv)
    run_main.last_fakes = fakes  # lets a test inspect e.g. whether append_to_log ran
    return code, out.getvalue() + err.getvalue()


CI = {"GITHUB_ACTIONS": "true"}
LOCAL: dict[str, str] = {}


class CiDetectionTests(unittest.TestCase):
    def test_detects_github_actions(self) -> None:
        with mock.patch.dict("os.environ", CI, clear=True):
            self.assertTrue(running_in_ci())

    def test_not_ci_when_variable_missing_or_empty(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(running_in_ci())
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": ""}, clear=True):
            self.assertFalse(running_in_ci())


class CiOutputTests(unittest.TestCase):
    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)  # undo the CI-mode logging switch-off

    def test_ci_run_prints_counts_and_no_private_text(self) -> None:
        code, output = run_main([], CI)
        self.assertEqual(code, 0)
        for private in PRIVATE_STRINGS:
            self.assertNotIn(private, output)
        self.assertIn("Found 1 newsletter(s)", output)
        self.assertIn("Summaries: 1 ok, 0 skipped (not newsletters), 0 unavailable.", output)
        self.assertIn("Stories kept: 1.", output)
        self.assertIn("Digest sent.", output)

    def test_ci_counts_failed_and_skipped_summaries(self) -> None:
        results = [fake_summary(), NewsletterSummary(stories=[], skip=True), f"(summary unavailable: {SECRET_ERROR})"]
        code, output = run_main([], CI, fetch_newsletters=mock.Mock(return_value=[fake_newsletter()] * 3),
                                summarize_all=mock.Mock(return_value=results))
        self.assertEqual(code, 0)
        self.assertIn("Summaries: 1 ok, 1 skipped (not newsletters), 1 unavailable.", output)
        self.assertNotIn(SECRET_ERROR, output)

    def test_ci_does_not_write_the_csv_log(self) -> None:
        run_main([], CI)
        run_main.last_fakes["append_to_log"].assert_not_called()

    def test_ci_still_sends_the_digest(self) -> None:
        run_main([], CI)
        run_main.last_fakes["send_digest"].assert_called_once()

    def test_local_run_still_prints_details_and_logs(self) -> None:
        code, output = run_main([], LOCAL)
        self.assertEqual(code, 0)
        self.assertIn(SECRET_SUBJECT, output)
        self.assertIn(SECRET_SENDER, output)
        run_main.last_fakes["append_to_log"].assert_called_once()

    def test_ci_no_newsletters_message(self) -> None:
        code, output = run_main([], CI, fetch_newsletters=mock.Mock(return_value=[]))
        self.assertEqual(code, 0)
        self.assertIn("No newsletters found", output)

    def test_ci_turns_logging_off(self) -> None:
        run_main([], CI)
        self.assertGreaterEqual(logging.root.manager.disable, logging.CRITICAL)


class CiErrorTests(unittest.TestCase):
    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def test_fetch_error_text_is_hidden_in_ci(self) -> None:
        code, output = run_main([], CI, connect=mock.Mock(side_effect=FetchError(f"Could not reach Gmail ({SECRET_ERROR})")))
        self.assertEqual(code, 1)
        self.assertNotIn(SECRET_ERROR, output)
        self.assertIn("FetchError", output)

    def test_send_error_text_is_hidden_in_ci(self) -> None:
        code, output = run_main([], CI, send_digest=mock.Mock(side_effect=SendError(f"refused {SECRET_ADDRESS}")))
        self.assertEqual(code, 1)
        self.assertNotIn(SECRET_ADDRESS, output)
        self.assertIn("SendError", output)

    def test_unexpected_crash_prints_only_the_type_in_ci(self) -> None:
        crash = mock.Mock(side_effect=ValueError(f"bad data from {SECRET_SENDER}"))
        code, output = run_main([], CI, summarize_all=crash)
        self.assertEqual(code, 1)
        self.assertNotIn(SECRET_SENDER, output)
        self.assertNotIn("Traceback", output)
        self.assertIn("ValueError", output)

    def test_config_error_names_missing_settings_in_ci(self) -> None:
        # ConfigError text has only setting NAMES, and is the useful hint for a missing secret.
        error = ConfigError("Missing setting(s): GMAIL_ADDRESS.")
        code, output = run_main([], CI, load_credentials=mock.Mock(side_effect=error))
        self.assertEqual(code, 1)
        self.assertIn("GMAIL_ADDRESS", output)

    def test_local_error_keeps_full_message(self) -> None:
        code, output = run_main([], LOCAL, connect=mock.Mock(side_effect=FetchError("Could not reach Gmail (offline)")))
        self.assertEqual(code, 1)
        self.assertIn("offline", output)

    def test_local_crash_is_not_swallowed(self) -> None:
        with self.assertRaises(ValueError):
            run_main([], LOCAL, summarize_all=mock.Mock(side_effect=ValueError("boom")))


class WorkflowFileTests(unittest.TestCase):
    """The workflow is plain text, so we check it as text (no YAML package needed)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        # Drop comments so a word inside a comment cannot satisfy or break a check.
        cls.code = "\n".join(line.split("#")[0] for line in cls.text.splitlines())

    def test_has_schedule_and_manual_button(self) -> None:
        self.assertRegex(self.code, r'cron:\s*"30 11 \* \* \*"')
        self.assertIn("workflow_dispatch:", self.code)

    def test_uses_python_312_with_pip_cache_and_requirements(self) -> None:
        self.assertIn('python-version: "3.12"', self.code)
        self.assertIn("cache: pip", self.code)
        self.assertIn("pip install -r requirements.txt", self.code)

    def test_runs_main_without_preview_or_no_send(self) -> None:
        self.assertIn("run: python src/main.py\n", self.code + "\n")
        self.assertNotIn("--preview", self.code)
        self.assertNotIn("--no-send", self.code)

    def test_reads_the_four_secrets(self) -> None:
        for name in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "GEMINI_API_KEY", "DIGEST_TO"):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", self.code)

    def test_no_real_secret_values_in_file(self) -> None:
        # Every ${{ }} expression must be a secret reference, nothing literal.
        for line in self.code.splitlines():
            if any(name in line for name in ("GMAIL_", "GEMINI_", "DIGEST_TO")):
                self.assertIn("secrets.", line)

    def test_least_privilege_permissions(self) -> None:
        self.assertRegex(self.code, r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("write", self.code.split("jobs:")[0].split("permissions:")[1])

    def test_concurrency_and_timeout(self) -> None:
        self.assertRegex(self.code, r"(?m)^concurrency:\n  group: \S+\n  cancel-in-progress: false$")
        self.assertRegex(self.code, r"timeout-minutes:\s*\d+")

    def test_no_artifacts_and_no_credentials_left_on_disk(self) -> None:
        self.assertNotIn("upload-artifact", self.code)
        self.assertIn("persist-credentials: false", self.code)

    def test_every_action_is_pinned_to_a_full_commit(self) -> None:
        uses = re.findall(r"uses:\s*(\S+)", self.code)
        self.assertTrue(uses)
        for reference in uses:
            self.assertRegex(reference, r"@[0-9a-f]{40}$")

    def test_secrets_only_on_the_run_step_not_job_wide(self) -> None:
        # The first "env:" in the file must belong to the last step, after all the "uses:" steps.
        self.assertGreater(self.code.index("env:"), self.code.rindex("uses:"))


if __name__ == "__main__":
    unittest.main()
