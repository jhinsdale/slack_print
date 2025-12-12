import tempfile
import unittest
import contextlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest import mock

import slack_print


class SlackPrintTests(unittest.TestCase):
    def test_slackdump_id_prefixed_screenshot_attachments(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            channel = root / "C123"
            channel.mkdir()
            for file_id, filename in (("F123", "Screenshot example 1.png"),
                                      ("F456", "Screenshot_example_2.png")):
                (channel / f"{file_id}-{filename}").write_bytes(b"png")
            # A plain-name match must not override the correct file ID.
            (root / "Screenshot example 1.png").write_bytes(b"wrong")
            message = {
                "ts": "1791803717.190829", "user": "U1", "text": "Review example:",
                "files": [
                    {"id": "F123", "name": "Screenshot example 1.png", "mimetype": "image/png",
                     "url_private": "https://files.slack.com/example1.png"},
                    {"id": "F456", "name": "Screenshot:example/2.png", "mimetype": "image/png",
                     "url_private_download": "https://files.slack.com/example2.png"},
                ],
            }
            output = root / "document.html"
            slack_print.make_document([message], message["ts"], None, root, output,
                                      slack_print.dt.timezone.utc)
            rendered = output.read_text()
            for filename in ("F123-Screenshot example 1.png", "F456-Screenshot_example_2.png"):
                self.assertIn(f'src="document-files/{filename}"', rendered)
                self.assertEqual((root / "document-files" / filename).read_bytes(), b"png")
            self.assertTrue(slack_print.has_linkable_files(
                [message], root, message["ts"], None, include_custom_emoji=False))

    def test_safe_zip_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            zip_path = root / "dump.zip"
            with zipfile.ZipFile(zip_path, "w") as zip_file:
                zip_file.writestr("channel/messages.json", "[]")
            destination = root / "out"
            with zipfile.ZipFile(zip_path) as zip_file:
                slack_print.extract_zip_safely(zip_file, destination)
            self.assertEqual((destination / "channel" / "messages.json").read_text(), "[]")

    def test_zip_path_traversal_is_rejected(self):
        for unsafe_name in ("../outside.json", "/absolute.json", "C:/windows.json", "..\\outside.json"):
            with self.subTest(unsafe_name=unsafe_name), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                zip_path = root / "dump.zip"
                with zipfile.ZipFile(zip_path, "w") as zip_file:
                    zip_file.writestr(unsafe_name, "[]")
                with zipfile.ZipFile(zip_path) as zip_file:
                    with self.assertRaisesRegex(ValueError, "unsafe ZIP member path"):
                        slack_print.extract_zip_safely(zip_file, root / "out")
                self.assertFalse((root / "outside.json").exists())

    def test_slackdump_detection(self):
        with mock.patch("slack_print.shutil.which", return_value=None):
            self.assertFalse(slack_print.slackdump_available())
        with mock.patch("slack_print.shutil.which", return_value="/usr/local/bin/slackdump"):
            self.assertTrue(slack_print.slackdump_available())

    def test_wkhtmltopdf_detection(self):
        with mock.patch("slack_print.shutil.which", return_value=None):
            self.assertFalse(slack_print.wkhtmltopdf_available())
        with mock.patch("slack_print.shutil.which", return_value="/usr/local/bin/wkhtmltopdf"):
            self.assertTrue(slack_print.wkhtmltopdf_available())

    def test_weasyprint_detection(self):
        with mock.patch("slack_print.shutil.which", return_value=None):
            self.assertFalse(slack_print.weasyprint_available())
        with mock.patch("slack_print.shutil.which", return_value="/usr/local/bin/weasyprint"):
            self.assertTrue(slack_print.weasyprint_available())

    def test_pdf_converter_selection_prefers_weasyprint(self):
        def which(name):
            return f"/usr/local/bin/{name}" if name in {"weasyprint", "wkhtmltopdf"} else None
        with mock.patch("slack_print.shutil.which", side_effect=which):
            self.assertEqual(slack_print.available_pdf_converters(), ["weasyprint", "wkhtmltopdf"])
            self.assertEqual(slack_print.default_pdf_converter(), "weasyprint")
            self.assertEqual(slack_print.resolve_pdf_converter("auto"), "weasyprint")
            self.assertEqual(slack_print.resolve_pdf_converter("wkhtmltopdf"), "wkhtmltopdf")
        with mock.patch("slack_print.shutil.which", return_value=None):
            self.assertIsNone(slack_print.resolve_pdf_converter("weasyprint"))

    def test_wkhtmltopdf_is_quiet_unless_verbose(self):
        quiet = slack_print.wkhtmltopdf_command(Path("input.html"), "output.pdf", False)
        verbose = slack_print.wkhtmltopdf_command(Path("input.html"), "output.pdf", True)
        very_verbose = slack_print.wkhtmltopdf_command(Path("input.html"), "output.pdf", True, True)
        self.assertIn("--quiet", quiet)
        self.assertNotIn("--quiet", verbose)
        self.assertNotIn("--quiet", very_verbose)
        self.assertEqual(very_verbose[very_verbose.index("--log-level") + 1], "info")
        self.assertEqual(quiet[quiet.index("--page-size") + 1], "Letter")
        self.assertEqual(quiet[quiet.index("--margin-left") + 1], "0.4in")
        self.assertEqual(quiet[quiet.index("--margin-right") + 1], "0.4in")
        self.assertIn("--disable-smart-shrinking", quiet)
        self.assertEqual(quiet[quiet.index("--load-error-handling") + 1], "ignore")
        self.assertEqual(quiet[quiet.index("--load-media-error-handling") + 1], "ignore")
        self.assertEqual(slack_print.wkhtmltopdf_output_options(False), {
            "stdout": slack_print.subprocess.PIPE,
            "stderr": slack_print.subprocess.PIPE,
        })
        self.assertEqual(slack_print.wkhtmltopdf_output_options(True), {})

    def test_weasyprint_command_is_quiet_unless_verbose(self):
        quiet = slack_print.weasyprint_command(Path("input.html"), "output.pdf", False)
        verbose = slack_print.weasyprint_command(Path("input.html"), "output.pdf", True)
        very_verbose = slack_print.weasyprint_command(Path("input.html"), "output.pdf", True, True)
        self.assertEqual(quiet[:2], ["weasyprint", "--quiet"])
        self.assertNotIn("--quiet", verbose)
        self.assertIn("--verbose", very_verbose)
        self.assertIn("--custom-metadata", quiet)
        self.assertIn("--media-type", quiet)
        self.assertEqual(quiet[quiet.index("--media-type") + 1], "print")
        self.assertIn("--base-url", quiet)
        self.assertEqual(quiet[-2:], ["input.html", "output.pdf"])
        self.assertEqual(slack_print.pdf_output_options(False), {
            "stdout": slack_print.subprocess.PIPE,
            "stderr": slack_print.subprocess.PIPE,
        })
        self.assertEqual(slack_print.pdf_output_options(False, True), {"stderr": slack_print.subprocess.PIPE})
        self.assertEqual(slack_print.pdf_output_options(True), {})

    def test_pdf_completely_absent_from_help_without_converter(self):
        stderr = io.StringIO()
        with mock.patch("slack_print.available_pdf_converters", return_value=[]), mock.patch.object(
            sys, "argv", ["slack_print.py", "--help"]
        ), contextlib.redirect_stdout(stderr):
            with self.assertRaises(SystemExit) as stopped:
                slack_print.main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertNotIn("pdf", stderr.getvalue().lower())

    def test_pdf_format_present_with_converter(self):
        output = io.StringIO()
        with mock.patch("slack_print.available_pdf_converters", return_value=["weasyprint"]), mock.patch.object(
            sys, "argv", ["slack_print.py", "--help"]
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                slack_print.main()
        self.assertIn("{html,markdown,pdf}", output.getvalue())
        self.assertIn("--pdf-converter {auto,weasyprint}", output.getvalue())
        self.assertNotIn("wkhtmltopdf}", output.getvalue())
        self.assertNotIn("--pdf ", output.getvalue())

    def test_help_groups_options_by_purpose(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["slack_print.py", "--help"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                slack_print.main()
        help_text = output.getvalue()
        for heading in (
            "Message selection:", "Slack input and authentication:",
            "Document content:", "Output and formatting:",
        ):
            self.assertIn(heading, help_text)
        self.assertIn("-R, --reactors", help_text)
        self.assertIn("-V, --no-previews", help_text)
        self.assertIn("-L, --no-post-links", help_text)
        self.assertNotIn("--no-link-previews", help_text)
        self.assertIn("-q, --quiet", help_text)
        self.assertIn("-vv, --very-verbose", help_text)
        self.assertIn("-P {auto,", help_text)
        self.assertIn("--pdf-converter", help_text)
        self.assertIn("-H, --debug-render-html", help_text)
        self.assertIn("-J, --debug-dump-json", help_text)
        self.assertIn("--user-highlight USER", help_text)
        self.assertIn("--user-highlight", help_text.split("Document content:")[1].split("Output and formatting:")[0])

    def test_quiet_and_verbose_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["slack_print.py", "-q", "-v"]), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as stopped:
                slack_print.main()
        self.assertNotEqual(stopped.exception.code, 0)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_quiet_and_very_verbose_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with mock.patch.object(
            sys, "argv", ["slack_print.py", "-q", "-vv"]
        ), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as stopped:
                slack_print.main()
        self.assertNotEqual(stopped.exception.code, 0)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_progress_respects_quiet(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            slack_print.progress("doing work...")
            slack_print.progress("hidden", quiet=True)
        self.assertEqual(stderr.getvalue(), "doing work...\n")

    def test_quiet_still_prints_written_file(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            output = root / "out.html"
            source.write_text(json.dumps([{"ts": "1712345678.000001", "text": "hello", "user": "U1"}]))
            stderr = io.StringIO()
            with mock.patch.object(
                sys, "argv",
                ["slack_print.py", "1712345678.000001", "-i", str(source), "-o", str(output), "-q"],
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            self.assertIn(f"Wrote {output}", stderr.getvalue())
            self.assertNotIn("Reading input data...", stderr.getvalue())
            self.assertNotIn("Preparing messages...", stderr.getvalue())

    def test_debug_dump_json_cli(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            output = root / "out.html"
            debug_json = root / "out-json-input.json"
            source.write_text(json.dumps([{"ts": "1712345678.000001", "text": "hello", "user": "U1"}]))
            stderr = io.StringIO()
            with mock.patch.object(
                sys, "argv",
                [
                    "slack_print.py", "1712345678.000001", "-i", str(source), "-o", str(output),
                    "-J", "-q",
                ],
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            self.assertEqual(json.loads(debug_json.read_text()), [[{"ts": "1712345678.000001", "text": "hello", "user": "U1"}]])
            self.assertIn(f"Wrote {output}", stderr.getvalue())

    def test_debug_json_path_and_write(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            destination = root / "document-json-input.json"
            self.assertEqual(
                slack_print.debug_dump_json_path(True, root / "document.pdf"),
                destination,
            )
            self.assertEqual(slack_print.debug_dump_json_path(True, Path("-")), Path("slack-print-json-input.json"))
            self.assertIsNone(slack_print.debug_dump_json_path(False, root / "document.pdf"))
            slack_print.write_debug_json([{"ok": True}], destination, False)
            self.assertEqual(json.loads(destination.read_text()), [{"ok": True}])
            with self.assertRaises(FileExistsError):
                slack_print.write_debug_json([], destination, False)
            slack_print.write_debug_json([], destination, True)
            self.assertEqual(json.loads(destination.read_text()), [])

    def test_stylesheet_profiles_keep_converter_workarounds_separate(self):
        html_css = slack_print.html_stylesheet()
        wkhtml_css = slack_print.html_stylesheet("wkhtmltopdf")
        self.assertIn(".emoji{display:inline-block", html_css)
        self.assertIn(".mention{color:#1264a3;background:#e8f5fa;text-decoration:none}", html_css)
        self.assertIn("@media print", html_css)
        self.assertNotIn(".reaction .emoji,.reaction-type .emoji{width:18px;height:18px", html_css)
        self.assertIn(".reaction .emoji,.reaction-type .emoji{width:18px;height:18px", wkhtml_css)

    def test_calendar_prefixes_use_utc_and_keep_slack_timestamps(self):
        import datetime as dt
        for prefix, expected in (
            ("2017", "2017-01-01T00:00:00+00:00"),
            ("201711", "2017-11-01T00:00:00+00:00"),
            ("20171103", "2017-11-03T00:00:00+00:00"),
            ("2017110312", "2017-11-03T12:00:00+00:00"),
            ("20171103123", "2017-11-03T12:30:00+00:00"),
            ("20171103123456", "2017-11-03T12:34:56+00:00"),
            ("20240229", "2024-02-29T00:00:00+00:00"),
        ):
            with self.subTest(prefix=prefix):
                channel, stamp = slack_print.parse_ref("@alice:" + prefix)
                self.assertEqual(channel, "@alice")
                self.assertEqual(dt.datetime.fromtimestamp(float(stamp), dt.timezone.utc).isoformat(), expected)
        self.assertEqual(slack_print.parse_ref("#foobar:20171103")[0], "#foobar")
        for username in ("Alice", "ALICE", "@Alice"):
            self.assertEqual(slack_print.parse_ref(username + ":2017010")[0], username)
        self.assertEqual(slack_print.parse_ref("alice:1509716102.000360"), ("alice", "1509716102.000360"))
        self.assertEqual(slack_print.parse_ref("p1509716102000360", "D123"), ("D123", "1509716102.000360"))
        for invalid in ("20230229", "202613", "2026010124", "202601011260", "0000", "202", "202601010000000"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                slack_print.parse_ref(invalid)

    def test_resolve_named_conversations_requires_unique_exact_matches(self):
        values = [{"members": [
            {"id": "U1", "name": "alice", "profile": {"display_name": "Alice Example"}},
            {"id": "U2", "name": "someone"},
        ]}, {"channels": [
            {"id": "D1", "is_im": True, "user": "U1"},
            {"id": "D2", "is_im": True, "user": "U2"},
            {"id": "C1", "name": "foobar", "is_private": False},
            {"id": "C2", "name": "secret", "is_private": True},
        ]}]
        for name in ("alice", "Alice", "ALICE", "@ALICE", "@Alice Example", "@U1"):
            self.assertEqual(slack_print.resolve_conversation(name, values), "D1")
        self.assertEqual(slack_print.resolve_conversation("#FOOBAR", values), "C1")
        for missing in ("@mi", "#secret", "#missing"):
            with self.assertRaises(ValueError):
                slack_print.resolve_conversation(missing, values)
        values[0]["members"][1]["profile"] = {"display_name": "alice"}
        with self.assertRaisesRegex(ValueError, "ambiguous user"):
            slack_print.resolve_conversation("@alice", values)
        self.assertEqual(slack_print.resolve_conversation("@U1", values), "D1")
        values[1]["channels"].append({"id": "D3", "user": "U1"})
        with self.assertRaisesRegex(ValueError, "ambiguous conversation"):
            slack_print.resolve_conversation("@U1", values)

    def test_live_named_calendar_range_resolves_before_dump_and_skips_boundary_threads(self):
        for selector, channel in (("@alice", "D1"), ("#foobar", "C1")):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as name:
                output = Path(name) / "document.html"
                commands = []
                def directory(root, workspace, *unused, **kwargs):
                    self.assertEqual(workspace, "example")
                    root.mkdir(parents=True, exist_ok=True)
                    (root / "directory.json").write_text(json.dumps([
                        {"id": "U1", "name": "alice"},
                        {"id": "D1", "user": "U1", "is_im": True},
                        {"id": "C1", "name": "foobar", "is_private": False},
                    ]))
                def dump(command, *unused, **kwargs):
                    commands.append(command)
                    root = Path(command[command.index("-o") + 1])
                    root.mkdir(parents=True, exist_ok=True)
                    (root / "messages.json").write_text(json.dumps([
                        {"ts": "1509716102.000360", "user": "U1", "text": "hello <#C1>", "channel_id": channel}
                    ]))
                    return mock.Mock()
                argv = ["slack_print.py", selector + ":20171103", channel + ":20171104",
                        "-w", "example", "-A", "-q", "-o", str(output)]
                stderr = io.StringIO()
                with mock.patch.object(sys, "argv", argv), mock.patch(
                    "slack_print.ensure_auth"
                ), mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                    "slack_print.fetch_user_directory", side_effect=directory
                ) as users, mock.patch("slack_print.fetch_channel_directory", side_effect=directory) as channels, mock.patch(
                    "slack_print.run_slackdump_dump", side_effect=dump
                ), contextlib.redirect_stderr(stderr):
                    self.assertEqual(slack_print.main(), 0)
                self.assertEqual(len(commands), 1)
                self.assertEqual(commands[0][-1], channel)
                self.assertEqual(commands[0][commands[0].index("-time-from") + 1], "2017-11-02T23:59:59")
                self.assertEqual(commands[0][commands[0].index("-time-to") + 1], "2017-11-04T00:00:01")
                self.assertNotIn("absent", stderr.getvalue())
                self.assertIn("hello", output.read_text())
                self.assertEqual(users.call_count, 1)
                channels.assert_called_once()
                self.assertEqual(channels.call_args.kwargs["channel_types"], "im" if selector.startswith("@") else "public_channel")
                self.assertNotIn("Fetching Slack channel names...", stderr.getvalue())
                self.assertIn("#foobar", output.read_text())

    def test_offline_named_date_requires_metadata_and_uses_it(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "input.json"
            source.write_text(json.dumps([
                {"id": "U1", "name": "alice"}, {"id": "D1", "user": "U1"},
                {"ts": "1509716102.000360", "user": "U1", "text": "offline hello"},
            ]))
            argv = ["slack_print.py", "20171103", "-c", "@alice", "-i", str(source),
                    "-o", str(root / "output.html"), "-A", "-q"]
            with mock.patch.object(sys, "argv", argv), mock.patch("slack_print.ensure_auth") as auth, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            auth.assert_not_called()
            self.assertIn("offline hello", (root / "output.html").read_text())

    def test_calendar_cli_errors_stop_before_authentication(self):
        for references, message in (
            (["D1:20230229"], "invalid UTC date prefix"),
            (["D1:202601", "202501"], "end must not be before start"),
            (["D1:202601", "--single-thread"], "requires a start message"),
        ):
            with self.subTest(references=references), mock.patch.object(
                sys, "argv", ["slack_print.py", *references]
            ), mock.patch("slack_print.ensure_auth") as auth, contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as result:
                    slack_print.main()
                self.assertEqual(result.exception.code, 2)
                self.assertIn(message, stderr.getvalue())
                auth.assert_not_called()

    def test_help_documents_named_conversations_and_utc_prefixes(self):
        with mock.patch.object(sys, "argv", ["slack_print.py", "--help"]), contextlib.redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as result:
                slack_print.main()
        self.assertEqual(result.exception.code, 0)
        for syntax in ("@alice", "#foobar", "YYYYMMDDHHMMSS in UTC", "4–14", "month/day default to 01"):
            self.assertIn(syntax, stdout.getvalue())

    def test_auth_announces_marked_default_even_with_login(self):
        for force in (False, True):
            with self.subTest(force=force), mock.patch(
                "slack_print.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="example\n* community\n", stderr=""),
            ), mock.patch("slack_print.authenticate") as authenticate, contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(slack_print.ensure_auth(None, force), "community")
                self.assertEqual(stderr.getvalue(), "USING DEFAULT WORKSPACE: community\n")
                if force:
                    authenticate.assert_called_once_with("community")
                else:
                    authenticate.assert_not_called()

    def test_auth_uses_sole_workspace_and_accepts_explicit_selection(self):
        for listing, hint, expected in (
            ("* example\n", None, "example"),
            ("* community\nexample\n", "example", "example"),
            ("* community\nexample\n", "https://example.slack.com", "https://example.slack.com"),
        ):
            with self.subTest(hint=hint, listing=listing), mock.patch(
                "slack_print.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=listing, stderr=""),
            ), mock.patch("slack_print.authenticate") as authenticate:
                self.assertEqual(slack_print.ensure_auth(hint, False), expected)
                authenticate.assert_not_called()
        with mock.patch("slack_print.subprocess.run") as run, mock.patch("slack_print.authenticate") as authenticate:
            self.assertEqual(slack_print.ensure_auth("example", True), "example")
            run.assert_not_called()
            authenticate.assert_called_once_with("example")

    def test_failed_workspace_listing_does_not_fall_back(self):
        with mock.patch("slack_print.subprocess.run", return_value=mock.Mock(returncode=1)), mock.patch(
            "slack_print.authenticate"
        ) as authenticate:
            with self.assertRaisesRegex(RuntimeError, "could not list saved Slack workspaces"):
                slack_print.ensure_auth(None, False)
            authenticate.assert_not_called()

    def test_cli_default_workspace_is_logged_in_quiet_mode_and_passed_to_dump(self):
        with tempfile.TemporaryDirectory() as name:
            def dump(command, *args, **kwargs):
                self.assertEqual(command[command.index("-workspace") + 1], "community")
                root = Path(command[command.index("-o") + 1])
                root.mkdir(parents=True)
                (root / "messages.json").write_text(json.dumps([
                    {"ts": "1509716102.000360", "user": "U1", "text": "hello"}
                ]))
            with mock.patch.object(sys, "argv", [
                "slack_print.py", "C1:20171103", "-A", "-I", "-q",
                "-o", str(Path(name) / "out.html")
            ]), mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="example\n* community\n", stderr=""),
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=dump), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(slack_print.main(), 0)
                self.assertIn("USING DEFAULT WORKSPACE: community", stderr.getvalue())

    def test_channel_without_start_fetches_all_without_prompts_or_time_bounds(self):
        for selector in ("D1", "@alice", "#foobar"):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as name:
                output = Path(name) / "out.html"
                channel = "C1" if selector.startswith("#") else "D1"
                def directory(root, *args, **kwargs):
                    root.mkdir(parents=True, exist_ok=True)
                    (root / "directory.json").write_text(json.dumps([
                        {"id": "U1", "name": "alice"}, {"id": "D1", "user": "U1"},
                        {"id": "C1", "name": "foobar"},
                    ]))
                def dump(command, *args, **kwargs):
                    self.assertNotIn("-time-from", command)
                    self.assertNotIn("-time-to", command)
                    self.assertEqual(command[-1], channel)
                    root = Path(command[command.index("-o") + 1])
                    root.mkdir(parents=True, exist_ok=True)
                    (root / "messages.json").write_text(json.dumps([
                        {"ts": "1509716102.000360", "user": "U1", "text": "first post"},
                        {"ts": "1712345678.123456", "user": "U1", "text": "last post"},
                    ]))
                with mock.patch.object(sys, "argv", [
                    "slack_print.py", "-c", selector, "-w", "example.slack.com", "-o", str(output), "-A", "-q"
                ]), mock.patch("builtins.input") as prompt, mock.patch("slack_print.ensure_auth"), mock.patch(
                    "slack_print.slackdump_available", return_value=True
                ), mock.patch("slack_print.fetch_user_directory", side_effect=directory), mock.patch(
                    "slack_print.fetch_channel_directory", side_effect=directory
                ), mock.patch("slack_print.run_slackdump_dump", side_effect=dump), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(slack_print.main(), 0)
                prompt.assert_not_called()
                self.assertNotIn("absent", stderr.getvalue())
                document = output.read_text()
                self.assertIn("first post", document)
                self.assertIn("last post", document)
                self.assertIn("/archives/" + channel + "/p1509716102000360", document)

    def test_prompt_ctrl_c_exits_without_traceback(self):
        with mock.patch.object(sys, "argv", ["slack_print.py"]), mock.patch(
            "builtins.input", side_effect=KeyboardInterrupt
        ), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as result:
                slack_print.main()
        self.assertEqual(result.exception.code, 130)
        self.assertIn("Cancelled", stderr.getvalue())

    def test_channel_without_start_rejects_single_thread(self):
        with mock.patch.object(sys, "argv", ["slack_print.py", "-c", "D1", "-1"]), mock.patch(
            "builtins.input"
        ) as prompt, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                slack_print.main()
        self.assertEqual(result.exception.code, 2)
        prompt.assert_not_called()

    def test_refs(self):
        self.assertEqual(
            slack_print.parse_ref("https://x.slack.com/archives/C123/p1712345678123456"),
            ("C123", "1712345678.123456"),
        )
        self.assertEqual(slack_print.parse_ref("C123:1712345678.123456"), ("C123", "1712345678.123456"))
        self.assertEqual(
            slack_print.workspace_hint("https://example.slack.com/archives/C123/p1712345678123456", None),
            "https://example.slack.com",
        )
        self.assertEqual(
            slack_print.slack_message_url(
                "https://example.slack.com/archives/C123/p1712345678123456", None,
                "C123", "1712345678.123456",
            ),
            "https://example.slack.com/archives/C123/p1712345678123456",
        )
        self.assertEqual(
            slack_print.slack_message_url("C123:1712345678.123456", "example.slack.com", "C123", "1712345678.123456"),
            "https://example.slack.com/archives/C123/p1712345678123456",
        )
        self.assertIsNone(slack_print.slack_message_url("C123:1712345678.123456", None, "C123", "1712345678.123456"))
        self.assertEqual(
            slack_print.related_slack_channel_url("https://example.slack.com/archives/C123/p1712345678123456", "C999"),
            "https://example.slack.com/archives/C999",
        )
        self.assertEqual(
            slack_print.related_slack_user_url("https://example.slack.com/archives/C123/p1712345678123456", "U123"),
            "https://example.slack.com/team/U123",
        )

    def test_early_date_and_message_url_name_output_from_first_included_message(self):
        with tempfile.TemporaryDirectory() as name:
            previous = Path.cwd()
            os.chdir(name)
            try:
                source = Path("input.json")
                source.write_text(json.dumps({
                    "channel_id": "D123", "channel_name": "DM-alice-bob",
                    "messages": [
                        {"ts": "1509716103.000001", "text": "later"},
                        {"ts": "1230768000.000001", "text": "before requested range"},
                        {"ts": "1509716102.000360", "text": "first included"},
                    ],
                }))
                expected = Path("DM-alice-bob-2017-11-03-13-35-02-to-2017-11-03-13-35-03.html")
                old_guess = Path("DM-alice-bob-2010-01-01-00-00-00.html")
                old_guess.write_text("keep old file")
                for reference in ("D123:20100101", "https://example.slack.com/archives/D123/p1509716102000360"):
                    argv = ["slack_print.py", reference, "-i", str(source), "-z", "UTC", "-A", "-q"]
                    if expected.exists():
                        argv.append("-F")
                    with mock.patch.object(sys, "argv", argv), mock.patch("builtins.input") as prompt, contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(slack_print.main(), 0)
                    prompt.assert_not_called()
                    self.assertTrue(expected.exists())
                    self.assertIn("first included", expected.read_text())
                    self.assertNotIn("before requested range", expected.read_text())
                    self.assertEqual(old_guess.read_text(), "keep old file")
                saved = expected.read_text()
                with mock.patch.object(sys, "argv", [
                    "slack_print.py", "D123:20100101", "-i", str(source), "-z", "UTC", "-A", "-q"
                ]), mock.patch.object(sys.stdin, "isatty", return_value=False), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit):
                        slack_print.main()
                self.assertIn(str(expected), stderr.getvalue())
                self.assertEqual(expected.read_text(), saved)
            finally:
                os.chdir(previous)

    def test_default_output_name(self):
        name = slack_print.default_output_name(
            "general", "1712345678.123456", slack_print.dt.timezone.utc, "markdown"
        )
        self.assertEqual(name, Path("general-2024-04-05-19-34-38-to-2024-04-05-19-34-38.md"))
        self.assertEqual(slack_print.clean_conversation_name("DM-user-alpha UserBeta", "D1"), "DM-user-alpha-UserBeta")

    def test_default_filename_end_includes_late_thread_replies(self):
        with tempfile.TemporaryDirectory() as name:
            previous = Path.cwd()
            os.chdir(name)
            try:
                source = Path("input.json")
                parent = "1712345678.123456"
                source.write_text(json.dumps({
                    "channel_id": "C123", "channel_name": "general", "messages": [
                        {"ts": parent, "text": "parent"},
                        {"ts": "1712432078.123456", "thread_ts": parent, "text": "late included reply"},
                        {"ts": "1712518478.123456", "text": "excluded later post"},
                    ],
                }))
                with mock.patch.object(sys, "argv", [
                    "slack_print.py", "C123:" + parent, parent, "-i", str(source), "-z", "UTC", "-A", "-q"
                ]), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(slack_print.main(), 0)
                output = Path("general-2024-04-05-19-34-38-to-2024-04-06-19-34-38.html")
                self.assertTrue(output.exists())
                self.assertIn("late included reply", output.read_text())
                self.assertNotIn("excluded later post", output.read_text())
            finally:
                os.chdir(previous)

    def test_output_format_inference(self):
        for filename, expected in (
            ("document.htm", "html"), ("document.html", "html"),
            ("document.md", "markdown"), ("document.markdown", "markdown"),
            ("document.pdf", "pdf"), ("document.unknown", "html"),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(slack_print.infer_output_format(Path(filename)), expected)

    def test_debug_render_html_path_uses_converter_name(self):
        self.assertEqual(
            slack_print.debug_render_html_path(True, Path("report.pdf"), "chrome"),
            Path("report-chrome-input.html"),
        )
        self.assertEqual(
            slack_print.debug_render_html_path(True, Path("-"), "weasyprint"),
            Path("slack-print-weasyprint-input.html"),
        )
        self.assertIsNone(slack_print.debug_render_html_path(False, Path("report.pdf"), "chrome"))

    def test_assets_path_uses_output_stem(self):
        self.assertEqual(slack_print.assets_path(Path("reports/foo.html")), Path("reports/foo-files"))
        self.assertEqual(slack_print.assets_path(Path("reports/foo.md")), Path("reports/foo-files"))

    def test_existing_output_requires_force(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "document.html"
            output.write_text("keep")
            with self.assertRaisesRegex(FileExistsError, "use -F/--force"):
                slack_print.require_available_output(output, False)
            slack_print.require_available_output(output, True)
            slack_print.require_available_output(Path("-"), False)

    def test_overwrite_error_comes_before_usage_with_blank_line(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "document.html"
            output.write_text("keep")
            stderr = io.StringIO()
            argv = ["slack_print.py", "C123:1712345678.123456", "-o", str(output)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(sys.stdin, "isatty", return_value=False), contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(SystemExit, "2"):
                    slack_print.main()
            message = stderr.getvalue()
            self.assertRegex(message, r"error: output already exists: .*use -F/--force to replace it\n\nusage:")

    def test_overwrite_prompt_declines_before_live_work(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "document.html"
            output.write_text("keep")
            argv = ["slack_print.py", "C123:1712345678.123456", "-o", str(output)]
            for answer in ("", "n", "no", "anything"):
                with self.subTest(answer=answer), mock.patch.object(sys, "argv", argv), mock.patch.object(
                    sys.stdin, "isatty", return_value=True
                ), mock.patch("builtins.input", return_value=answer) as prompt, mock.patch(
                    "slack_print.ensure_auth"
                ) as auth, mock.patch("slack_print.run_slackdump_dump") as fetch, contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit):
                        slack_print.main()
                    prompt.assert_called_once()
                    auth.assert_not_called()
                    fetch.assert_not_called()
                    self.assertIn(str(output), stderr.getvalue())
                    self.assertIn("-F/--force", stderr.getvalue())
                    self.assertEqual(output.read_text(), "keep")

    def test_overwrite_accepts_once_and_force_skips_prompt(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{"ts": "1712345678.123456", "text": "new text"}]))
            output = root / "document.html"
            debug = root / "document-json-input.json"
            for answer, force in (("y", False), ("yes", False), ("", True)):
                with self.subTest(answer=answer, force=force):
                    output.write_text("old")
                    debug.write_text("old")
                    argv = ["slack_print.py", "C123:1712345678.123456", "-i", str(source),
                            "-o", str(output), "-J", "-A", "-q"] + (["-F"] if force else [])
                    with mock.patch.object(sys, "argv", argv), mock.patch.object(
                        sys.stdin, "isatty", return_value=True
                    ), mock.patch("builtins.input", return_value=answer) as prompt, contextlib.redirect_stderr(io.StringIO()) as stderr:
                        self.assertEqual(slack_print.main(), 0)
                    self.assertEqual(prompt.call_count, 0 if force else 1)
                    action = "Overwrote (force given)" if force else "Wrote"
                    self.assertIn(f"{action} {output} (1 posts)", stderr.getvalue())
                    if not force:
                        self.assertIn(str(output), stderr.getvalue())
                        self.assertIn(str(debug), stderr.getvalue())
                    self.assertIn("new text", output.read_text())
                    self.assertIsInstance(json.loads(debug.read_text()), list)

    def test_force_summary_tracks_actual_output_replacement(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{"ts": "1712345678.123456", "text": "hello"}]))
            for target in ("document.html", "document.md", "document.pdf", "debug", "-"):
                for exists in (False, True):
                    with self.subTest(target=target, exists=exists):
                        output = root / ("debug.pdf" if target == "debug" else target)
                        actual_output = root / "debug-weasyprint-input.html" if target == "debug" else output
                        if exists:
                            actual_output.write_text("old")
                        else:
                            actual_output.unlink(missing_ok=True)
                        argv = ["slack_print.py", "C123:1712345678.123456", "-i", str(source),
                                "-o", "-" if target == "-" else str(output), "--force", "-A", "-q"]
                        if target == "debug":
                            argv.append("-H")
                        with mock.patch.object(sys, "argv", argv), mock.patch(
                            "slack_print.available_pdf_converters", return_value=["weasyprint"]
                        ), mock.patch("slack_print.subprocess.run"), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
                            self.assertEqual(slack_print.main(), 0)
                        action = "Overwrote (force given)" if exists and target != "-" else "Wrote"
                        destination = "stdout" if target == "-" else str(actual_output)
                        self.assertEqual(stderr.getvalue(), f"{action} {destination} (1 posts)\n")

    def test_default_pdf_overwrite_declines_after_fetch_before_emoji_and_render(self):
        with tempfile.TemporaryDirectory() as name:
            previous = Path.cwd()
            os.chdir(name)
            try:
                output = Path("DM-hin-2026-10-12-12-40-50-to-2026-10-12-12-40-50.pdf")
                output.write_text("keep")
                start = str(slack_print.dt.datetime(
                    2026, 10, 12, 12, 40, 50, tzinfo=slack_print.dt.timezone.utc
                ).timestamp())
                argv = ["slack_print.py", f"D123:{start}", "-f", "pdf", "-z", "UTC"]

                def fake_dump(command, *args, **kwargs):
                    root = Path(command[command.index("-o") + 1])
                    root.mkdir(parents=True)
                    (root / "messages.json").write_text(json.dumps({
                        "channel_id": "D123", "members": ["hin"],
                        "messages": [{"ts": start, "text": "hello"}],
                    }))

                for answer in ("", KeyboardInterrupt()):
                    with self.subTest(answer=answer), mock.patch.object(sys, "argv", argv), mock.patch.object(
                        sys.stdin, "isatty", return_value=True
                    ), mock.patch("builtins.input", **(
                        {"side_effect": answer} if isinstance(answer, KeyboardInterrupt) else {"return_value": answer}
                    )) as prompt, mock.patch("slack_print.available_pdf_converters", return_value=["weasyprint"]), mock.patch(
                        "slack_print.slackdump_available", return_value=True
                    ), mock.patch("slack_print.ensure_auth") as auth, mock.patch(
                        "slack_print.run_slackdump_dump", side_effect=fake_dump
                    ) as fetch, mock.patch("slack_print.fetch_user_directory"), mock.patch(
                        "slack_print.fetch_custom_emoji"
                    ) as emoji, mock.patch("slack_print.fetch_standard_emoji_data") as standard, contextlib.redirect_stderr(io.StringIO()) as stderr:
                        with self.assertRaises(SystemExit):
                            slack_print.main()
                        prompt.assert_called_once()
                        auth.assert_called_once()
                        fetch.assert_called_once()
                        emoji.assert_not_called()
                        standard.assert_not_called()
                        self.assertIn(
                            f"Output already exists: {output}.\n"
                            "In the future, you can use -F/--force to skip this prompt and force overwrite.\n"
                            f'Overwrite "{output}"? [y/N] ', stderr.getvalue(),
                        )
                        self.assertIn("Checking Slack authentication", stderr.getvalue())
                        self.assertEqual(output.read_text(), "keep")
            finally:
                os.chdir(previous)

    def test_default_output_approval_after_loading_leaves_other_files_untouched(self):
        with tempfile.TemporaryDirectory() as name:
            previous = Path.cwd()
            os.chdir(name)
            try:
                start = "1712345678.123456"
                output = slack_print.default_output_name("general", start, slack_print.dt.timezone.utc, "html")
                unrelated = slack_print.default_output_name("other-channel", start, slack_print.dt.timezone.utc, "html")
                source = Path("messages.json")
                source.write_text(json.dumps({"channel_id": "C123", "channel_name": "general", "messages": [
                    {"ts": start, "text": "new text"},
                ]}))
                output.write_text("old")
                unrelated.write_text("keep unrelated")
                argv = ["slack_print.py", f"C123:{start}", "-i", str(source), "-z", "UTC", "-A", "-q"]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(
                    sys.stdin, "isatty", return_value=True
                ), mock.patch("builtins.input", return_value="yes") as prompt, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(slack_print.main(), 0)
                    prompt.assert_called_once()
                self.assertIn("new text", output.read_text())
                self.assertEqual(unrelated.read_text(), "keep unrelated")
            finally:
                os.chdir(previous)

    def test_user_highlight_matches_handles_names_and_ids(self):
        values = [{"users": [
            {"id": "U1", "name": "hin", "profile": {"display_name": "John H", "real_name": "John Hinsdale"}},
            {"id": "U2", "name": "other", "profile": {"display_name": "Other"}},
        ]}]
        for username in ("hin", "@HIN", "John H", "John Hinsdale", "U1"):
            with self.subTest(username=username):
                self.assertEqual(slack_print.highlighted_user_ids(values, username), {"U1"})
        self.assertEqual(slack_print.highlighted_user_ids(values, "missing"), set())
        self.assertEqual(slack_print.highlighted_user_ids(values, None), set())

    def test_user_highlight_covers_whole_posts_and_replies(self):
        messages = [
            {"ts": "1712345678.000001", "user": "U1", "text": "parent"},
            {"ts": "1712345679.000001", "user": "U2", "thread_ts": "1712345678.000001", "text": "other reply"},
            {"ts": "1712345680.000001", "user": "U1", "thread_ts": "1712345678.000001", "text": "matching reply", "reactions": [{"name": "thumbsup", "count": 1}]},
            {"ts": "1712345681.000001", "user": "U1", "thread_ts": "1712345677.000001", "text": "orphan"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for output_format in ("html",):
                with self.subTest(output_format=output_format):
                    output = root / f"document.{output_format}"
                    slack_print.make_document(
                        messages, messages[0]["ts"], None, root, output, slack_print.dt.timezone.utc,
                        False, output_format, highlight_users={"U1"},
                    )
                    page = output.read_text()
                    self.assertEqual(page.count('class="user-highlight"'), 3)
                    for message in messages:
                        opening = f'<article id="{slack_print.post_id(message["ts"])}"'
                        if message["user"] == "U1":
                            self.assertIn(opening + ' class="user-highlight" style="background-color:#e8f4ff">', page)
                        else:
                            self.assertNotIn(opening + ' class="user-highlight"', page)
                    self.assertIn("matching reply</div>", page)
                    self.assertIn("reactions", page)

    def test_user_highlight_cli_and_no_posts_warning_after_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps({"users": [{"id": "U1", "name": "hin"}], "messages": [
                {"ts": "1712345678.000001", "user": "U1", "text": "parent"},
                {"ts": "1712345679.000001", "user": "U2", "text": "other"},
            ]}))
            for username, start, matches in (("hin", "1712345678.000001", True), ("missing", "1712345678.000001", False), ("hin", "1712345679.000001", False)):
                with self.subTest(username=username, start=start):
                    argv = ["slack_print.py", f"C1:{start}", "-i", str(source), "-o", "-", "-A", "-q", "-U", username]
                    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                        self.assertEqual(slack_print.main(), 0)
                    self.assertEqual('class="user-highlight"' in stdout.getvalue(), matches)
                    warning = f'warning: no posts were found for user "{username}"'
                    if matches:
                        self.assertNotIn(warning, stderr.getvalue())
                    else:
                        self.assertIn(warning, stderr.getvalue())
                        self.assertGreater(stderr.getvalue().index(warning), stderr.getvalue().index("Wrote stdout"))

    def test_user_highlight_is_ignored_with_warning_for_markdown(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{ "ts": "1712345678.000001", "user": "U1", "text": "*post*"}]))
            argv = ["slack_print.py", "C1:1712345678.000001", "-i", str(source), "-o", "-", "-f", "markdown", "-A", "-q", "-U", "U1"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(slack_print.main(), 0)
            self.assertIn("**post**", stdout.getvalue())
            self.assertNotIn("user-highlight", stdout.getvalue())
            self.assertIn("user highlighting is not supported in Markdown; -U/--user-highlight ignored", stderr.getvalue())
            self.assertNotIn("no posts were found", stderr.getvalue())

    def test_user_highlight_reaches_pdf_converter_html(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{ "ts": "1712345678.000001", "user": "U1", "text": "pdf"}]))
            argv = ["slack_print.py", "C1:1712345678.000001", "-i", str(source), "-o", str(root / "doc.pdf"), "-A", "--user-highlight", "U1"]

            def fake_pdf(command, **kwargs):
                page = Path(command[-2]).read_text()
                self.assertIn('class="user-highlight" style="background-color:#e8f4ff"', page)
                self.assertIn("print-color-adjust:exact", page)

            with mock.patch("slack_print.available_pdf_converters", return_value=["weasyprint"]), mock.patch(
                "slack_print.subprocess.run", side_effect=fake_pdf
            ) as converter, mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
                converter.assert_called_once()

    def test_conversation_name(self):
        self.assertEqual(slack_print.conversation_name([{"channel_id": "C1", "channel_name": "team chat"}], "C1"), "team-chat")
        label, people = slack_print.conversation_info(
            [{"channel_id": "D1", "channel_name": "Direct message", "members": ["U1", {"id": "U2"}]}], "D1"
        )
        self.assertEqual(label, "Direct message")
        self.assertEqual(people, ["U1", "U2"])
        self.assertEqual(slack_print.conversation_heading("general", "C1"), "Slack: #general")
        self.assertEqual(slack_print.conversation_heading("Direct message", "D1"), "Slack: Direct message")
        self.assertEqual(slack_print.conversation_heading("D3LRKBLCC", "D3LRKBLCC"), "Slack: Direct message")
        self.assertEqual(
            slack_print.resolved_conversation_label("D3LRKBLCC", "D3LRKBLCC", [{"user": "U1"}], {"U1": "user-alpha"}),
            "DM-user-alpha",
        )
        self.assertEqual(
            slack_print.resolved_conversation_label(
                "D3LRKBLCC", "D3LRKBLCC", [{"user": "U1"}],
                {"U1": "user-alpha", "U2": "User Beta"}, ["U1", "U2"],
            ),
            "DM-user-alpha-UserBeta",
        )

    def test_inferred_dm_name_excludes_app_authors_but_keeps_app_posts(self):
        messages = [
            {"ts": "1712345678.000001", "user": "U1", "text": "hello"},
            {"ts": "1712345679.000001", "bot_id": "B123", "text": "app content"},
            {"ts": "1712345680.000001", "user": "U2", "text": "reply"},
            {"user": "U3", "bot_id": "B456"},
            {"user": "U4", "bot_profile": {"name": "Helper"}},
            {"user": "U5", "app_id": "A123"},
            {"user": "U6", "subtype": "bot_message"},
            {"user": "B789"},
            {"username": "Helper"},
        ]
        users = {"U1": "Alice", "U2": "Bob"}
        self.assertEqual(slack_print.resolved_conversation_label(None, "D123", messages, users), "DM-Alice-Bob")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            count = slack_print.make_document(
                messages[:3], "1712345678.000001", None, root, root / "out.html",
                slack_print.dt.timezone.utc, False, users=users, channel_id="D123",
            )
            self.assertEqual(count, 3)
            document = (root / "out.html").read_text()
            self.assertIn("Slack: DM-Alice-Bob", document)
            self.assertIn("app content", document)
            self.assertIn("B123 [app]", document)

    def test_bot_user_profiles_are_excluded_from_dm_name(self):
        directory = [{"members": [
            {"id": "U1", "name": "Alice"}, {"id": "U2", "name": "Bob"},
            {"id": "U3", "name": "Helper", "is_bot": True},
            {"id": "U4", "name": "App", "is_app_user": True},
            {"id": "U5", "name": "ProfileBot", "profile": {"bot_id": "B123"}},
            {"id": "USLACKBOT", "name": "Slackbot"},
        ]}]
        bots = slack_print.bot_user_ids(directory)
        self.assertEqual(bots, {"USLACKBOT", "U3", "U4", "U5"})
        users = slack_print.user_names(directory)
        messages = [{"user": user} for user in ("U1", "USLACKBOT", "U3", "U2", "U4", "U5")]
        self.assertEqual(slack_print.resolved_conversation_label(
            None, "D123", messages, users, bot_users=bots,
        ), "DM-Alice-Bob")
        self.assertEqual(slack_print.resolved_conversation_label(
            None, "D123", [], users, ["U1", "USLACKBOT", "U3", "U2"], bots,
        ), "DM-Alice-Bob")
        self.assertEqual(slack_print.resolved_conversation_label(
            None, "D123", [{"user": "U1"}, {"user": "USLACKBOT"}], users,
        ), "DM-Alice")

    def test_bot_only_dm_fallback_has_no_bot_id_in_name(self):
        self.assertEqual(slack_print.resolved_conversation_label(
            None, "D123", [{"bot_id": "B123", "text": "hello"}],
        ), "Direct message")

    def test_mpdm_name_is_friendly(self):
        users = {"@caseyexample": "Casey Example"}
        raw = "mpdm-user-alpha--user-beta--caseyexample--user-gamma-1"
        self.assertEqual(
            slack_print.friendly_conversation_label(raw, users),
            "DM-user-alpha-user-beta-CaseyExample-user-gamma",
        )
        self.assertEqual(
            slack_print.conversation_heading(raw, "G1", users=users),
            "Slack: DM-user-alpha-user-beta-CaseyExample-user-gamma",
        )
        self.assertEqual(
            slack_print.conversation_name([{"channel_id": "G1", "channel_name": raw}], "G1", users),
            "DM-user-alpha-user-beta-CaseyExample-user-gamma",
        )

    def test_user_names_and_mentions(self):
        values = [{"users": [
            {"id": "U1", "name": "fallback", "profile": {"display_name": "User Alpha", "real_name": "User Alpha"}},
            {"id": "U2", "profile": {"real_name": "User Beta"}},
            {"id": "U3", "profile": {"display_name": "Build Bot", "bot_id": "B123"}},
        ]}]
        users = slack_print.user_names(values)
        self.assertEqual(users, {
            "U1": "User Alpha", "@fallback": "User Alpha", "U2": "User Beta",
            "U3": "Build Bot", "B123": "Build Bot",
        })
        self.assertEqual(slack_print.author({"user": "U1"}, users), "User Alpha")
        self.assertEqual(slack_print.author({"bot_id": "B123"}, users), "Build Bot [app]")
        self.assertEqual(slack_print.author({"bot_id": "B999", "username": "GitLab"}, users), "GitLab [app]")
        self.assertEqual(
            slack_print.author({"bot_id": "B999", "bot_profile": {"name": "GitLab App"}}, users),
            "GitLab App [app]",
        )
        self.assertIn("@User Beta", slack_print.mrkdwn("hello <@U2>", users))
        self.assertEqual(slack_print.markdown_text("hello <@U2>", users), "hello @User Beta")
        self.assertEqual(
            slack_print.mrkdwn(
                "hello <@U2>", users,
                header_url="https://example.slack.com/archives/C1/p1712345678123456",
            ),
            'hello <a class="mention" href="https://example.slack.com/team/U2">@User Beta</a>',
        )

    def test_channel_names_and_mentions(self):
        values = [{"channels": [
            {"id": "C1H10Q22Z", "name": "incident-room"},
            {"channel_id": "G2PRIVATE", "channel_name": "private-planning"},
        ]}]
        channels = slack_print.channel_names(values)
        self.assertEqual(channels, {"C1H10Q22Z": "incident-room", "G2PRIVATE": "private-planning"})
        self.assertEqual(
            slack_print.mrkdwn("thread from <#C1H10Q22Z> at 8:30a", channels=channels),
            'thread from <span class="mention">#incident-room</span> at 8:30a',
        )
        self.assertEqual(
            slack_print.mrkdwn(
                "thread from <#C1H10Q22Z> at 8:30a",
                channels=channels,
                header_url="https://example.slack.com/archives/D1/p1712345678123456",
            ),
            'thread from <a class="mention" href="https://example.slack.com/archives/C1H10Q22Z">#incident-room</a> at 8:30a',
        )
        self.assertEqual(slack_print.markdown_text("<#G2PRIVATE>", channels=channels), "#private-planning")
        self.assertEqual(slack_print.mrkdwn("<#CUNKNOWN>"), '<span class="mention">#CUNKNOWN</span>')

    def test_message_channel_ids_detects_rendered_mentions(self):
        messages = [{
            "ts": "1712345678.000001",
            "text": "thread from <#C1H10Q22Z> at 8:30a",
            "blocks": [{"type": "rich_text", "elements": [
                {"type": "rich_text_section", "elements": [{"type": "channel", "channel_id": "G2PRIVATE"}]}
            ]}],
            "attachments": [{"text": "see <#C3ATTACH>"}],
        }]
        self.assertEqual(slack_print.message_channel_ids(messages), {"C1H10Q22Z", "G2PRIVATE", "C3ATTACH"})
        self.assertEqual(slack_print.message_channel_ids([{"ts": "1", "channel_id": "CNOTMENTIONED", "text": "plain"}]), set())

    def test_emoji_alias_uses_inline_code_style(self):
        self.assertEqual(slack_print.mrkdwn("looks good :thumbsup:"), "looks good 👍")
        self.assertEqual(slack_print.markdown_text("looks good :thumbsup:"), "looks good 👍")
        self.assertEqual(slack_print.rendered_emoji("+1::skin-tone-2", None, False), "👍🏻")
        self.assertEqual(slack_print.rendered_emoji("heart_hands::skin-ton-4", None, False), "🫶🏽")
        self.assertIn("1f9b8-200d-2640-fe0f.svg", slack_print.unicode_emoji_image("🦸‍♀️"))
        self.assertEqual(slack_print.mrkdwn(":partying_face: :clinking_glasses: :flag-us: :cake:"), "🥳 🥂 🇺🇸 🎂")
        self.assertEqual(slack_print.mrkdwn(":goat: :female_superhero: :coffee: :hammer_and_wrench: :droplet:"), "🐐 🦸‍♀️ ☕ 🛠️ 💧")
        self.assertEqual(slack_print.mrkdwn("unknown :not_real:"), "unknown <code>:not_real:</code>")

    def test_reactions_include_counts_and_resolved_names(self):
        message = {"reactions": [
            {"name": "thumbsup", "count": 2, "users": ["U1", "U2"]},
            {"name": "party_parrot", "count": 1, "users": ["U1"]},
        ]}
        users = {"U1": "User Alpha", "U2": "User Beta"}
        emojis = {"party_parrot": "files/emoji/party.gif"}
        page = slack_print.render_reactions(message, users, emojis)
        self.assertIn("jdecked/twemoji@17.0.3/assets/svg/1f44d.svg", page)
        self.assertNotIn('width="18"', page)
        wkhtml_page = slack_print.render_reactions(message, users, emojis, emoji_image_format="background")
        self.assertIn("jdecked/twemoji@17.0.3/assets/72x72/1f44d.png", wkhtml_page)
        self.assertIn('class="emoji emoji-bg"', wkhtml_page)
        self.assertNotIn("<img", wkhtml_page)
        self.assertIn(" 2</span>", page)
        self.assertIn('title="User Alpha, User Beta"', page)
        self.assertIn('class="emoji"', page)
        toned_reaction = slack_print.render_reactions({"reactions": [
            {"name": "heart_hands::skin-tone-4", "count": 1, "users": ["U1"]},
        ]}, users, emojis)
        self.assertIn("jdecked/twemoji@17.0.3/assets/svg/1faf6-1f3fd.svg", toned_reaction)
        self.assertNotIn(":heart_hands::skin-tone-4:", toned_reaction)
        html_css = slack_print.html_stylesheet()
        weasy_css = slack_print.html_stylesheet("weasyprint")
        self.assertNotIn(".reactions{display:block}.reactions>.reaction", html_css)
        self.assertIn(
            ".reactions{display:block}.reactions>.reaction{display:inline-block;margin:0 .3rem .3rem 0;border:0",
            weasy_css,
        )
        self.assertIn(".reactions.extended .reaction{display:inline-block", weasy_css)
        self.assertIn(".reactions.extended.stacked .reaction{display:block}", weasy_css)
        self.assertIn(".reactions.extended .reaction-type{display:inline-block;border:0", weasy_css)
        markdown = slack_print.render_reactions(message, users, emojis, markdown=True)
        self.assertIn("👍 2 (User Alpha, User Beta)", markdown)
        self.assertIn("![:party_parrot:](files/emoji/party.gif) 1 (User Alpha)", markdown)
        detailed = slack_print.render_reactions(message, users, emojis, list_reactors=True)
        self.assertIn('class="reactions extended"', detailed)
        self.assertNotIn(":thumbsup:", detailed)
        self.assertIn('jdecked/twemoji@17.0.3/assets/svg/1f44d.svg', detailed)
        self.assertIn(' 2</span><span class="reactor-names">', detailed)
        self.assertIn('<span class="reactor-names">(<strong>User Alpha, User Beta</strong>)</span>', detailed)
        detailed_markdown = slack_print.render_reactions(message, users, emojis, markdown=True, list_reactors=True)
        self.assertIn("👍 2 (**User Alpha, User Beta**)", detailed_markdown)
        crowded = {"reactions": [
            {"name": "thumbsup", "count": 8, "users": [f"U{i}" for i in range(8)]},
            {"name": "heart", "count": 8, "users": [f"V{i}" for i in range(8)]},
        ]}
        crowded_users = {user_id: user_id.lower() for reaction in crowded["reactions"] for user_id in reaction["users"]}
        self.assertIn('class="reactions extended stacked"', slack_print.render_reactions(crowded, crowded_users, list_reactors=True))
        crowded_markdown = slack_print.render_reactions(crowded, crowded_users, markdown=True, list_reactors=True)
        self.assertIn(")\n", crowded_markdown)
        word_threshold = {"reactions": [{"name": "heart", "count": 5, "users": ["U1", "U2", "U3", "U4", "U5"]}]}
        eight_words = {"U1": "User Alpha", "U2": "User Beta", "U3": "UserC", "U4": "UserD", "U5": "User Echo"}
        nine_words = {**eight_words, "U5": "User Echo Extra"}
        self.assertNotIn("stacked", slack_print.render_reactions(word_threshold, eight_words, list_reactors=True))
        self.assertIn('class="reactions extended stacked"', slack_print.render_reactions(word_threshold, nine_words, list_reactors=True))

    def test_link_preview_rendering(self):
        message = {"attachments": [{
            "service_name": "Example News",
            "title": "A useful story",
            "title_link": "https://example.com/story?a=1&b=2",
            "text": "Short *summary*.",
            "thumb_url": "https://example.com/thumb.png",
            "fields": [{"title": "Author", "value": "User Alpha"}],
        }]}
        page = slack_print.render_previews(message)
        self.assertIn('class="link-preview"', page)
        self.assertIn("Example News", page)
        self.assertIn('href="https://example.com/story?a=1&amp;b=2"', page)
        self.assertIn("<strong>summary</strong>", page)
        self.assertIn('class="preview-image"', page)
        markdown = slack_print.render_previews(message, markdown=True)
        self.assertIn("> **Example News**", markdown)
        self.assertIn("> [A useful story](https://example.com/story?a=1&b=2)", markdown)
        self.assertIn("> **Author:** User Alpha", markdown)
        self.assertIn("> ![A useful story](https://example.com/thumb.png)", markdown)

    def test_suppressed_previews_are_not_rendered(self):
        for flag, value in (
            ("is_removed", True),
            ("is_hidden", "true"),
            ("preview_hidden", 1),
            ("hide_unfurl", "yes"),
        ):
            with self.subTest(flag=flag):
                message = {"attachments": [{
                    flag: value,
                    "service_name": "Wikipedia",
                    "title": "Truthiness",
                    "title_link": "https://en.wikipedia.org/wiki/Truthiness",
                    "text": "Truthiness is...",
                }]}
                self.assertEqual(slack_print.render_previews(message), "")
                self.assertEqual(slack_print.render_previews(message, markdown=True), "")

    def test_link_preview_hide_color_is_not_suppressed(self):
        message = {"attachments": [{
            "hide_color": True,
            "service_name": "Example",
            "title": "Visible preview",
            "title_link": "https://example.com",
        }]}
        self.assertIn("Visible preview", slack_print.render_previews(message))

    def test_previews_can_be_disabled(self):
        messages = [{
            "ts": "1712345678.000001",
            "user": "U1",
            "text": "<https://example.com>",
            "attachments": [{
                "service_name": "Example",
                "title": "Visible preview",
                "title_link": "https://example.com",
            }],
        }]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            html_output = root / "document.html"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, html_output, slack_print.dt.timezone.utc,
                include_previews=False,
            )
            page = html_output.read_text()
            self.assertIn('href="https://example.com"', page)
            self.assertNotIn("Visible preview", page)
            self.assertNotIn('class="link-preview"', page)

            md_output = root / "document.md"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, md_output, slack_print.dt.timezone.utc,
                output_format="markdown", include_previews=False,
            )
            markdown = md_output.read_text()
            self.assertIn("<https://example.com>", markdown)
            self.assertNotIn("Visible preview", markdown)

    def test_html_encoded_markdown_quote_is_not_double_escaped(self):
        text = "Thanks!\n\n&gt; 1. Is this installable?\nYes!"
        self.assertEqual(slack_print.markdown_text(text), "Thanks!\n\n> 1. Is this installable?\nYes!")
        self.assertIn("&gt; 1. Is this installable?", slack_print.mrkdwn(text))
        self.assertNotIn("&amp;gt;", slack_print.mrkdwn(text))

    def test_block_kit_rich_text_rendering(self):
        message = {
            "text": "plain fallback",
            "blocks": [{
                "type": "rich_text",
                "elements": [
                    {"type": "rich_text_section", "elements": [
                        {"type": "text", "text": "Hello ", "style": {"bold": True}},
                        {"type": "user", "user_id": "U1"},
                        {"type": "text", "text": " in "},
                        {"type": "channel", "channel_id": "C1"},
                    ]},
                    {"type": "rich_text_quote", "elements": [{"type": "text", "text": "quoted text"}]},
                    {"type": "rich_text_list", "style": "ordered", "elements": [
                        {"type": "rich_text_section", "elements": [{"type": "text", "text": "First"}]},
                        {"type": "rich_text_section", "elements": [{"type": "link", "url": "https://example.com", "text": "Second"}]},
                    ]},
                    {"type": "rich_text_preformatted", "elements": [{"type": "text", "text": "x < y"}]},
                ],
            }],
        }
        page = slack_print.render_blocks(
            message, {"U1": "User Alpha"}, channels={"C1": "general"},
            header_url="https://example.slack.com/archives/C2/p1712345678123456",
        )
        self.assertIn("<strong>Hello </strong>", page)
        self.assertIn('<a class="mention" href="https://example.slack.com/team/U1">@User Alpha</a>', page)
        self.assertIn('<a class="mention" href="https://example.slack.com/archives/C1">#general</a>', page)
        self.assertIn("<blockquote>quoted text</blockquote>", page)
        css = slack_print.html_stylesheet()
        self.assertIn("blockquote+blockquote{margin-top:-.5rem}", css)
        self.assertIn("blockquote:empty{display:none}", css)
        self.assertIn("blockquote>ol,blockquote>ul{margin:0;padding-left:1.3rem}", css)
        self.assertIn("<ol><li>First</li>", page)
        self.assertIn("<pre><code>x &lt; y</code></pre>", page)
        self.assertNotIn("plain fallback", page)
        markdown = slack_print.render_blocks(message, {"U1": "User Alpha"}, markdown=True, channels={"C1": "general"})
        self.assertIn("**Hello **@User Alpha in #general", markdown)
        self.assertIn("> quoted text", markdown)
        self.assertIn("1. First", markdown)
        self.assertIn("[Second](https://example.com)", markdown)
        self.assertIn("```\nx < y\n```", markdown)

    def test_quoted_numbered_line_wins_over_misclassified_rich_list(self):
        message = {
            "text": "Thanks!\n\n&gt; 1. Is this installable?\nYes!",
            "blocks": [{"type": "rich_text", "elements": [
                {"type": "rich_text_section", "elements": [{"type": "text", "text": "Thanks!"}]},
                {"type": "rich_text_list", "style": "ordered", "border": 1, "elements": [
                    {"type": "rich_text_section", "elements": [
                        {"type": "text", "text": "Is this installable?", "style": {"bold": True}}
                    ]}
                ]},
                {"type": "rich_text_section", "elements": [{"type": "text", "text": "Yes!"}]},
            ]}],
        }
        page = slack_print.render_blocks(message)
        self.assertIn("<blockquote><ol><li><strong>Is this installable?</strong></li></ol></blockquote>", page)
        markdown = slack_print.render_blocks(message, markdown=True)
        self.assertIn("> 1. **Is this installable?**", markdown)

    def test_unknown_block_preserves_visible_label(self):
        message = {"blocks": [{"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Approve"}}]}]}
        self.assertEqual(slack_print.render_blocks(message), "Approve")

    def test_fetch_user_directory_command(self):
        with tempfile.TemporaryDirectory() as name, mock.patch("slack_print.run_slackdump_with_progress") as run:
            root = Path(name) / "dump"
            slack_print.fetch_user_directory(root, "work")
            run.assert_called_once_with(
                [
                    "slackdump", "list", "users", "-q", "-y", "-format", "JSON",
                    "-workspace", "work",
                ],
                False,
                False,
                "fetching Slack user names",
                advisory_after=60,
                advisory="Note: use -I/--raw-user-ids to skip user-name lookup and show raw Slack user IDs.",
                cwd=root,
            )

    def test_fetch_channel_directory_command(self):
        with tempfile.TemporaryDirectory() as name, mock.patch("slack_print.run_slackdump_with_progress") as run:
            root = Path(name) / "dump"
            slack_print.fetch_channel_directory(root, "work")
            run.assert_called_once_with(
                [
                    "slackdump", "list", "channels", "-q", "-y", "-format", "JSON",
                    "-workspace", "work",
                ],
                False,
                False,
                "fetching Slack channel names",
                cwd=root,
            )

    def test_channel_lookup_filters_types_and_disables_channel_cache(self):
        for types, label in (("im", "fetching Slack DM channels"),
                             ("public_channel", "fetching Slack channel names"),
                             ("im,public_channel", "fetching Slack channel names")):
            with self.subTest(types=types), tempfile.TemporaryDirectory() as name, mock.patch(
                "slack_print.run_slackdump_with_progress"
            ) as run:
                slack_print.fetch_channel_directory(Path(name), "example", channel_types=types)
                command = run.call_args.args[0]
                self.assertEqual(command[command.index("-chan-types") + 1], types)
                self.assertIn("-no-chan-cache", command)
                self.assertEqual(run.call_args.args[3], label)

    def test_fetch_custom_emoji_command(self):
        with tempfile.TemporaryDirectory() as name, mock.patch("slack_print.run_slackdump_with_progress") as run:
            root = Path(name) / "dump"
            slack_print.fetch_custom_emoji(root, "work")
            run.assert_called_once_with(
                ["slackdump", "emoji", "-o", str(root / "custom-emoji"), "-files=false", "-workspace", "work"],
                False,
                False,
                "fetching Slack custom emoji list (image downloads have not started)",
            )

    def test_rate_limit_message_extracts_wait_time(self):
        self.assertEqual(
            slack_print.rate_limit_message(
                'time=now level=INFO msg="got rate limited, sleeping" retry_after=30s'
            ),
            "Slackdump is rate limited; waiting 30s...",
        )
        self.assertEqual(
            slack_print.rate_limit_message("error: slack rate limit exceeded, retry after 45s"),
            "Slackdump is rate limited; waiting 45s...",
        )
        self.assertIsNone(slack_print.rate_limit_message("ordinary progress"))

    def test_very_verbose_slackdump_directory_commands(self):
        with tempfile.TemporaryDirectory() as name, mock.patch("slack_print.run_slackdump_with_progress") as run:
            root = Path(name) / "dump"
            slack_print.fetch_user_directory(root, "work", True, True)
            self.assertIn("-v", run.call_args.args[0])
            self.assertNotIn("-q", run.call_args.args[0])
            run.reset_mock()
            slack_print.fetch_channel_directory(root, "work", True, True)
            self.assertIn("-v", run.call_args.args[0])
            self.assertNotIn("-q", run.call_args.args[0])
            run.reset_mock()
            slack_print.fetch_custom_emoji(root, "work", True, True)
            self.assertIn("-v", run.call_args.args[0])

    def test_selected_emoji_downloads_only_used_images_and_resolves_aliases(self):
        messages = [
            {"ts": "1", "text": ":outside:"},
            {"ts": "2", "text": ":alias_two:", "reactions": [{"name": "reaction", "count": 1}]},
            {"ts": "3", "text": ":outside:"},
            {"ts": "4", "thread_ts": "2", "blocks": [{"type": "emoji", "name": "block"}]},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            emoji_root = root / "custom-emoji"
            emoji_root.mkdir()
            index = {
                "alias_two": "alias:alias_one", "alias_one": "alias:party",
                "party": "https://example.com/party.gif?version=2",
                "reaction": "https://example.com/reaction.png",
                "block": "https://example.com/block.png",
                "outside": "https://example.com/outside.png",
            }
            (emoji_root / "index.json").write_text(json.dumps(index))
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"image"
            with mock.patch("slack_print.urllib.request.urlopen", return_value=response) as fetch:
                selected = slack_print.select_messages(messages, "2", "2")
                slack_print.download_selected_emoji(root, slack_print.message_emoji_names(selected))
            self.assertEqual({call.args[0] for call in fetch.call_args_list}, {
                index["party"], index["reaction"], index["block"],
            })
            self.assertEqual(fetch.call_count, 3)
            self.assertTrue((emoji_root / "emojis" / "party.gif").exists())
            self.assertFalse((emoji_root / "emojis" / "outside.png").exists())
            assets = slack_print.custom_emoji_assets(root, root / "document-files", {"alias_two"})
            self.assertEqual(assets["alias_two"], "document-files/emoji/party.gif")
            single = slack_print.select_messages(messages, "2", "3", True)
            self.assertEqual([m["ts"] for m in single], ["2"])

    def test_selected_emoji_skips_cycles_unsafe_names_and_retries_next_run(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            emoji_root = root / "custom-emoji"
            emoji_root.mkdir()
            (emoji_root / "index.json").write_text(json.dumps({
                "loop": "alias:loop", "bad": "alias:../escape",
                "../escape": "https://example.com/escape.png",
                "broken": "https://example.com/broken.png",
                "duplicate": "alias:broken", "local": "file:///etc/passwd",
            }))
            wanted = {"loop", "bad", "broken", "duplicate", "local", "missing"}
            with mock.patch("slack_print.urllib.request.urlopen", side_effect=OSError("offline")) as fetch, contextlib.redirect_stderr(io.StringIO()):
                slack_print.download_selected_emoji(root, wanted)
                self.assertEqual(fetch.call_count, 1)
                slack_print.download_selected_emoji(root, wanted)
                self.assertEqual(fetch.call_count, 2)
            self.assertFalse((emoji_root / "emojis" / "broken.png").exists())

    def test_emoji_progress_counts_success_failure_elapsed_and_quiet(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "custom-emoji").mkdir()
            (root / "custom-emoji" / "index.json").write_text(json.dumps({
                "good": "https://example.com/good.png",
                "bad": "https://example.com/bad.png",
            }))
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"image"
            stderr = io.StringIO()
            with mock.patch("slack_print.urllib.request.urlopen", side_effect=[OSError("offline"), response]), mock.patch("slack_print.time.monotonic", side_effect=[100, 100, 103, 108]), contextlib.redirect_stderr(stderr):
                slack_print.download_selected_emoji(root, {"good", "bad"})
            self.assertIn("Downloaded 0/2 emoji after 0 seconds", stderr.getvalue())
            self.assertIn("Downloaded 1/2 emoji after 8 seconds; 1 failed", stderr.getvalue())
            stderr = io.StringIO()
            with mock.patch("slack_print.urllib.request.urlopen", return_value=response), contextlib.redirect_stderr(stderr):
                slack_print.download_selected_emoji(root, {"good"}, quiet=True)
            self.assertEqual(stderr.getvalue(), "")

    def test_emoji_cache_reuses_refreshes_and_isolates_workspaces(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cache = root / "cache" / "work"
            index = {"party": "https://example.com/party.gif"}
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"image"

            def run(number, entries, workspace_cache=cache):
                source = root / str(number)
                (source / "custom-emoji").mkdir(parents=True)
                (source / "custom-emoji" / "index.json").write_text(json.dumps(entries))
                slack_print.download_selected_emoji(source, {"party", "new"}, True, workspace_cache)
                return source

            with mock.patch("slack_print.urllib.request.urlopen", return_value=response) as fetch:
                run(1, index)
                self.assertEqual(fetch.call_count, 1)
                source = run(2, index)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual((source / "custom-emoji" / "emojis" / "party.gif").read_bytes(), b"image")
                changed = {"party": "https://example.com/party-v2.gif", "new": "https://example.com/new.png"}
                run(3, changed)
                self.assertEqual(fetch.call_count, 3)
                run(4, changed, root / "cache" / "other")
                self.assertEqual(fetch.call_count, 5)
                source = run(5, {"new": changed["new"]})
                self.assertEqual(fetch.call_count, 5)
                self.assertFalse((source / "custom-emoji" / "emojis" / "party.gif").exists())
                for image in cache.glob("new-*"):
                    image.unlink()
                run(6, changed)
                self.assertEqual(fetch.call_count, 6)
            self.assertFalse(list(cache.glob(".emoji-*")))

    def test_emoji_cache_failure_does_not_break_download(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "custom-emoji").mkdir()
            (root / "custom-emoji" / "index.json").write_text(json.dumps({"party": "https://example.com/party.gif"}))
            cache = root / "not-a-directory"
            cache.write_text("occupied")
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"image"
            with mock.patch("slack_print.urllib.request.urlopen", return_value=response), contextlib.redirect_stderr(io.StringIO()):
                slack_print.download_selected_emoji(root, {"party"}, True, cache)
            self.assertTrue((root / "custom-emoji" / "emojis" / "party.gif").exists())

    def test_emoji_cache_resolves_current_workspace_without_credentials(self):
        with mock.patch("slack_print.subprocess.run", return_value=mock.Mock(stdout="other\n*work\n")) as run:
            self.assertEqual(slack_print.emoji_cache_directory(None), Path("/tmp/slack-emoji/work"))
            self.assertEqual(run.call_args.args[0], ["slackdump", "workspace", "list", "-b"])
        self.assertEqual(slack_print.emoji_cache_directory("https://work.slack.com"), Path("/tmp/slack-emoji/work"))
        self.assertIsNone(slack_print.emoji_cache_directory("../escape"))
        with mock.patch("slack_print.subprocess.run", side_effect=OSError("unavailable")):
            self.assertIsNone(slack_print.emoji_cache_directory(None))

    def test_custom_emoji_asset_and_rendering(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "custom-emoji" / "emojis"
            source.mkdir(parents=True)
            (source / "party_parrot.gif").write_bytes(b"GIF89a")
            (source / "unused.png").write_bytes(b"PNG")
            (root / "custom-emoji" / "emoji.json").write_text(json.dumps({
                "party_alias": "alias:party_parrot",
                "external_standard": "https://emoji.example/standard.png",
            }))
            (root / "custom-emoji" / "standard-emoji.json").write_text(json.dumps([{
                "unified": "1F984",
                "short_name": "unicorn_face",
                "short_names": ["unicorn", "unicorn_face"],
            }]))
            assets = root / "document-files"
            assets.mkdir()
            emojis = slack_print.custom_emoji_assets(root, assets, {"party_alias", "external_standard", "unicorn"})
            self.assertEqual(emojis, {
                "party_parrot": "document-files/emoji/party_parrot.gif",
                "party_alias": "document-files/emoji/party_parrot.gif",
                "external_standard": "https://emoji.example/standard.png",
                "unicorn": "https://cdn.jsdelivr.net/gh/jdecked/twemoji@17.0.3/assets/svg/1f984.svg",
            })
            self.assertFalse((assets / "emoji" / "unused.png").exists())
            self.assertEqual(slack_print.message_emoji_names([{"text": "ship :party_parrot:", "blocks": [{"type": "emoji", "name": "block_emoji"}]}]), {"party_parrot", "block_emoji"})
            rendered = slack_print.mrkdwn("ship it :party_alias:", custom_emoji=emojis)
            self.assertIn('class="emoji"', rendered)
            self.assertIn('alt=":party_alias:"', rendered)
            self.assertIn("![:party_alias:](document-files/emoji/party_parrot.gif)", slack_print.markdown_text("ship it :party_alias:", custom_emoji=emojis))
            self.assertEqual(slack_print.mrkdwn(":missing:", custom_emoji=emojis), "<code>:missing:</code>")

    def test_standard_emoji_data_fetch_is_run_local(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"[]"
        with tempfile.TemporaryDirectory() as name, mock.patch("slack_print.urllib.request.urlopen", return_value=response) as open_url:
            root = Path(name) / "dump"
            slack_print.fetch_standard_emoji_data(root)
            self.assertEqual((root / "custom-emoji" / "standard-emoji.json").read_bytes(), b"[]")
            open_url.assert_called_once_with(slack_print.STANDARD_EMOJI_DATA_URL, timeout=20)

    def test_quiet_slackdump_captures_output(self):
        with mock.patch("slack_print.subprocess.run") as run:
            slack_print.run_slackdump(["slackdump", "dump"], False)
            run.assert_called_once_with(
                ["slackdump", "dump"], check=True, text=True,
                stdout=slack_print.subprocess.PIPE, stderr=slack_print.subprocess.PIPE,
            )

    def test_verbose_slackdump_inherits_output(self):
        with mock.patch("slack_print.subprocess.run") as run:
            slack_print.run_slackdump(["slackdump", "dump"], True)
            run.assert_called_once_with(["slackdump", "dump"], check=True)

    def test_thread_and_range(self):
        messages = [
            {"ts": "1712345678.123456", "user": "U1", "text": "*parent*"},
            {"ts": "1712345679.000001", "thread_ts": "1712345678.123456", "user": "U2", "text": "reply"},
            {"ts": "1712345680.000001", "user": "U3", "text": "outside"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            count = slack_print.make_document(
                messages, "1712345678.123456", "1712345679.000001", root, output, slack_print.dt.timezone.utc
            )
            page = output.read_text()
            self.assertEqual(count, 2)
            self.assertNotIn(".reaction .emoji,.reaction-type .emoji{width:18px;height:18px", page)
            self.assertIn("<strong>parent</strong>", page)
            self.assertIn('<a class="post-time" href="#p1712345678123456"><time', page)
            self.assertNotIn('>p1712345678123456</a>', page)
            self.assertIn('<hr><footer>Created with Slack Print by John K. Hinsdale of Princeton Junction, NJ USA', page)
            self.assertIn('<ul class="thread">', page)
            self.assertIn(".thread{list-style:none", page)
            self.assertIn('.thread>li::before{content:""', page)
            self.assertIn('width:.35rem;height:.35rem;border-radius:50%;background:#777', page)
            self.assertIn("p1712345679000001", page)
            self.assertNotIn("outside", page)

    def test_range_includes_late_replies_to_selected_thread_parents(self):
        messages = [
            {"ts": "1712345678.000001", "user": "U1", "text": "start parent"},
            {"ts": "1712345680.000001", "user": "U2", "text": "end parent"},
            {
                "ts": "1712345699.000001", "thread_ts": "1712345680.000001",
                "user": "U3", "text": "late end reply",
            },
            {"ts": "1712345700.000001", "user": "U4", "text": "outside parent"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            count = slack_print.make_document(
                messages, "1712345678.000001", "1712345680.000001", root, output,
                slack_print.dt.timezone.utc,
            )
            page = output.read_text()
            self.assertEqual(count, 3)
            self.assertIn("start parent", page)
            self.assertIn("end parent", page)
            self.assertIn("late end reply", page)
            self.assertNotIn("outside parent", page)

    def test_html_title_and_metadata_use_heading_and_bounds(self):
        messages = [
            {"ts": "1712345678.123456", "user": "U1", "text": "start"},
            {"ts": "1712345679.000001", "user": "U2", "text": "end"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            slack_print.make_document(
                messages, "1712345678.123456", "1712345679.000001", root, output,
                slack_print.dt.timezone.utc, conversation_label="ai-tools", channel_id="C1",
            )
            page = output.read_text()
            title = "Slack: #ai-tools 2024-04-05 19:34:38 UTC"
            self.assertIn(f"<title>{title}</title>", page)
            self.assertIn(f'<meta name="title" content="{title}">', page)
            self.assertIn('<meta name="author" content="Slack Print">', page)
            self.assertIn('<meta name="description" content="Slack: #ai-tools">', page)
            self.assertIn('<meta name="subject" content="Slack: #ai-tools">', page)
            self.assertRegex(page, r'<meta name="dcterms\.created" content="[^"]+">')
            self.assertIn(
                '<meta name="generator" content="Slack Print by John K. Hinsdale">',
                page,
            )

    def test_edited_and_deleted_message_markers(self):
        messages = [
            {
                "ts": "1712345678.000001", "user": "U1", "text": "changed",
                "edited": {"user": "U1", "ts": "1712345688.000001"},
            },
            {"ts": "1712345679.000001", "user": "U2", "subtype": "message_deleted"},
            {"ts": "1712345680.000001", "user": "U3", "text": "redacted", "is_deleted": True},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            html_output = root / "index.html"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, html_output, slack_print.dt.timezone.utc
            )
            page = html_output.read_text()
            self.assertIn('<span class="message-meta">edited 2024-04-05 19:34:48 UTC</span>', page)
            self.assertIn('<span class="message-meta">deleted</span>', page)
            self.assertEqual(page.count('<p class="deleted-marker">This message was deleted.</p>'), 2)
            self.assertIn('redacted<p class="deleted-marker">This message was deleted.</p></div>', page)

            markdown_output = root / "index.md"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, markdown_output, slack_print.dt.timezone.utc,
                output_format="markdown",
            )
            markdown = markdown_output.read_text()
            self.assertIn("_edited 2024-04-05 19:34:48 UTC_", markdown)
            self.assertIn("_deleted_", markdown)
            self.assertEqual(markdown.count("*This message was deleted.*"), 2)

    def test_wkhtmltopdf_profile_uses_background_reaction_emoji(self):
        messages = [{
            "ts": "1712345678.123456", "user": "U1", "text": "react",
            "reactions": [{"name": "white_check_mark", "count": 1, "users": ["U1"]}],
        }]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            slack_print.make_document(
                messages, "1712345678.123456", None, root, output, slack_print.dt.timezone.utc,
                users={"U1": "User Alpha"}, style_profile="wkhtmltopdf",
            )
            page = output.read_text()
            self.assertIn("jdecked/twemoji@17.0.3/assets/72x72/2705.png", page)
            self.assertIn('class="emoji emoji-bg"', page)
            self.assertNotIn('src="https://cdn.jsdelivr.net/gh/jdecked/twemoji', page)

    def test_debug_render_html_writes_converter_input_without_conversion(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{
                "ts": "1712345678.123456", "channel_id": "D1", "user": "U1",
                "text": "react",
                "reactions": [{"name": "white_check_mark", "count": 1, "users": ["U1"]}],
            }]))
            pdf_output = root / "document.pdf"
            debug_html = root / "document-wkhtmltopdf-input.html"
            debug_json = root / "document-json-input.json"
            stderr = io.StringIO()
            argv = [
                "slack_print.py", "D1:1712345678.123456", "-i", str(source),
                "-o", str(pdf_output), "-P", "wkhtmltopdf", "-H", "-J",
            ]
            with mock.patch("slack_print.available_pdf_converters", return_value=["wkhtmltopdf"]), mock.patch(
                "slack_print.subprocess.run"
            ) as run, mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            run.assert_not_called()
            page = debug_html.read_text()
            self.assertIn("jdecked/twemoji@17.0.3/assets/72x72/2705.png", page)
            self.assertIn('class="emoji emoji-bg"', page)
            self.assertIn(f"Wrote {debug_html}", stderr.getvalue())
            self.assertFalse(pdf_output.exists())
            self.assertEqual(json.loads(debug_json.read_text())[0][0]["text"], "react")

    def test_pdf_auto_uses_weasyprint_when_available(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([{"ts": "1712345678.123456", "channel_id": "D1", "user": "U1", "text": "pdf"}]))
            pdf_output = root / "document.pdf"
            argv = [
                "slack_print.py", "D1:1712345678.123456", "-i", str(source),
                "-o", str(pdf_output), "-f", "pdf",
            ]
            stderr = io.StringIO()
            with mock.patch(
                "slack_print.available_pdf_converters", return_value=["weasyprint", "wkhtmltopdf"]
            ), mock.patch("slack_print.subprocess.run") as run, mock.patch.object(
                sys, "argv", argv
            ), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "weasyprint")
            self.assertIn("--quiet", command)
            self.assertEqual(command[-1], str(pdf_output.resolve()))
            self.assertIn("Converting HTML to PDF with weasyprint...", stderr.getvalue())

    def test_very_verbose_implies_verbose_and_echoes_full_slackdump_command(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            seen = {}

            def fake_run(command, verbose, *unused, **kwargs):
                seen["command"] = command
                seen["verbose"] = verbose
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([{
                    "ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "plain",
                }]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A", "-vv",
                "--workspace", "example.slack.com",
            ]
            stderr = io.StringIO()
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            self.assertTrue(seen["verbose"])
            self.assertIn("-v", seen["command"])
            self.assertEqual(seen["command"][-1], "C1")
            self.assertIn("running: slackdump dump", stderr.getvalue())
            self.assertIn("-log", stderr.getvalue())
            self.assertNotIn("<conversation>", stderr.getvalue())

    def test_live_url_selects_workspace_for_all_slackdump_fetches(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "document.html"
            seen = []

            def fake_run(command, verbose, *unused, **kwargs):
                seen.append(command)
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([{
                    "ts": "1783605537.451609", "channel_id": "D023MT0LGKC",
                    "user": "U1", "text": "see <#C2PROD>",
                }]))
                return mock.Mock()

            argv = [
                "slack_print.py",
                "https://example.slack.com/archives/D023MT0LGKC/p1783605537451609",
                "-o", str(output), "-q",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ) as ensure_auth, mock.patch(
                "slack_print.run_slackdump_dump", side_effect=fake_run
            ), mock.patch("slack_print.fetch_user_directory") as fetch_users, mock.patch(
                "slack_print.fetch_custom_emoji"
            ) as fetch_emoji, mock.patch(
                "slack_print.fetch_channel_directory"
            ) as fetch_channels, mock.patch(
                "slack_print.fetch_standard_emoji_data"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)

            ensure_auth.assert_called_once_with("https://example.slack.com", False)
            self.assertEqual(seen[0][seen[0].index("-workspace") + 1], "example")
            self.assertEqual(fetch_users.call_args.args[1], "example")
            self.assertEqual(fetch_emoji.call_args.args[1], "example")
            fetch_channels.assert_not_called()

    def test_live_url_rejects_conflicting_workspace_before_fetch(self):
        argv = [
            "slack_print.py",
            "https://example.slack.com/archives/D023MT0LGKC/p1783605537451609",
            "--workspace", "community",
        ]
        stderr = io.StringIO()
        with mock.patch("slack_print.slackdump_available") as available, mock.patch.object(
            sys, "argv", argv
        ), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                slack_print.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--workspace community conflicts with Slack URL workspace example", stderr.getvalue())
        available.assert_not_called()

    def test_live_urls_reject_different_workspaces_before_fetch(self):
        argv = [
            "slack_print.py",
            "https://example.slack.com/archives/D023MT0LGKC/p1783605537451609",
            "https://community.slack.com/archives/D023MT0LGKC/p1783605537451610",
        ]
        stderr = io.StringIO()
        with mock.patch("slack_print.slackdump_available") as available, mock.patch.object(
            sys, "argv", argv
        ), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                slack_print.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("start and end posts belong to different workspaces", stderr.getvalue())
        available.assert_not_called()

    def test_live_fetch_passes_user_api_config_to_slackdump_dump(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            api_config = root / "api.toml"
            api_config.write_text("workers = 1\n", encoding="utf-8")
            seen = {}

            def fake_run(command, verbose, *unused, **kwargs):
                seen["command"] = command
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([{
                    "ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "plain",
                }]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A", "-q",
                "--workspace", "example.slack.com", "--api-config", str(api_config),
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            self.assertEqual(seen["command"][seen["command"].index("-api-config") + 1], str(api_config.resolve()))

    def test_live_no_custom_emoji_skips_emoji_fetches(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"

            def fake_run(command, verbose, *unused, **kwargs):
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([{
                    "ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "plain",
                }]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-E", "-q",
                "--workspace", "example.slack.com",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch("slack_print.fetch_custom_emoji") as fetch_emoji, mock.patch(
                "slack_print.fetch_standard_emoji_data"
            ) as fetch_standard, mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            fetch_emoji.assert_not_called()
            fetch_standard.assert_not_called()

    def test_live_single_thread_fetch_uses_thread_target(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            seen = {}

            def fake_run(command, verbose, *unused, **kwargs):
                seen["command"] = command
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([
                    {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "parent"},
                    {
                        "ts": "1712345679.000001", "channel_id": "C1",
                        "thread_ts": "1712345678.000001", "user": "U2", "text": "reply",
                    },
                ]))
                return mock.Mock()

            argv = [
                "slack_print.py", "https://example.slack.com/archives/C1/p1712345678000001", "-o", str(output), "-A", "-q",
                "-1", "--workspace", "example.slack.com",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            self.assertEqual(seen["command"][-1], "C1:1712345678.000001")
            self.assertIn("-legacy", seen["command"])
            self.assertNotIn("-time-from", seen["command"])
            self.assertNotIn("-time-to", seen["command"])

    def test_live_single_thread_uses_channel_scan_fallback_after_exact_thread_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            seen = []

            def fake_run(command, verbose, *unused, **kwargs):
                seen.append(command)
                if len(seen) == 1:
                    raise subprocess.CalledProcessError(1, command)
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([
                    {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "parent"},
                    {
                        "ts": "1712345679.000001", "channel_id": "C1",
                        "thread_ts": "1712345678.000001", "user": "U2", "text": "reply",
                    },
                ]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A",
                "--single-thread", "--workspace", "example.slack.com",
            ]
            stderr = io.StringIO()
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[0][-1], "C1:1712345678.000001")
            self.assertIn("-legacy", seen[0])
            self.assertEqual(seen[1][-1], "C1")
            self.assertIn("-time-from", seen[1])
            self.assertIn("Direct Slack thread fetch failed; retrying slower channel range fetch...", stderr.getvalue())

    def test_live_single_thread_informs_when_slow_channel_scan_fallback_runs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            seen = []

            def fake_run(command, verbose, *unused, **kwargs):
                seen.append(command)
                if len(seen) == 1:
                    raise subprocess.CalledProcessError(1, command)
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([
                    {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "parent"},
                    {
                        "ts": "1712345679.000001", "channel_id": "C1",
                        "thread_ts": "1712345678.000001", "user": "U2", "text": "reply",
                    },
                ]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A",
                "--single-thread", "--workspace", "example.slack.com",
            ]
            stderr = io.StringIO()
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(slack_print.main(), 0)
            self.assertEqual(seen[-1][-1], "C1")
            self.assertIn("-time-from", seen[-1])
            self.assertIn("Direct Slack thread fetch failed; retrying slower channel range fetch...", stderr.getvalue())

    def test_live_range_fetches_boundary_threads_without_end_time_cap(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"
            seen = []

            def fake_run(command, verbose, *unused, **kwargs):
                seen.append(command)
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                target = command[-1]
                if target == "C1":
                    messages = [
                        {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "start parent"},
                        {"ts": "1712345680.000001", "channel_id": "C1", "user": "U2", "text": "end parent"},
                    ]
                elif target == "C1:1712345680.000001":
                    messages = [{
                        "ts": "1712345699.000001", "channel_id": "C1",
                        "thread_ts": "1712345680.000001", "user": "U3", "text": "late end reply",
                    }]
                else:
                    messages = []
                (dump_root / "messages.json").write_text(json.dumps(messages))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "C1:1712345680.000001",
                "-o", str(output), "-A", "-q", "--workspace", "example.slack.com",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)

            self.assertEqual([command[-1] for command in seen], [
                "C1", "C1:1712345678.000001", "C1:1712345680.000001",
            ])
            self.assertIn("-time-from", seen[0])
            self.assertIn("-time-to", seen[0])
            self.assertNotIn("-time-to", seen[1])
            self.assertNotIn("-time-to", seen[2])
            self.assertIn("late end reply", output.read_text())

    def test_live_fetch_skips_channel_directory_without_channel_mentions(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"

            def fake_run(command, verbose, *unused, **kwargs):
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([
                    {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "plain"},
                    {"ts": "1712345677.000001", "channel_id": "C1", "user": "U1", "text": "outside <#C2PROD>"},
                ]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A", "-q",
                "--workspace", "example.slack.com",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch("slack_print.fetch_channel_directory") as fetch_channels, mock.patch.object(
                sys, "argv", argv
            ), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            fetch_channels.assert_not_called()

    def test_live_fetch_keeps_channel_ids_without_fetching_directory_for_mentions(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.html"

            def fake_run(command, verbose, *unused, **kwargs):
                dump_root = Path(command[command.index("-o") + 1])
                dump_root.mkdir(parents=True, exist_ok=True)
                (dump_root / "messages.json").write_text(json.dumps([
                    {"ts": "1712345678.000001", "channel_id": "C1", "user": "U1", "text": "see <#C2PROD>"}
                ]))
                return mock.Mock()

            argv = [
                "slack_print.py", "C1:1712345678.000001", "-o", str(output), "-A", "-q",
                "--workspace", "example.slack.com",
            ]
            with mock.patch("slack_print.slackdump_available", return_value=True), mock.patch(
                "slack_print.ensure_auth"
            ), mock.patch("slack_print.run_slackdump_dump", side_effect=fake_run), mock.patch(
                "slack_print.fetch_user_directory"
            ), mock.patch("slack_print.fetch_channel_directory") as fetch_channels, mock.patch.object(
                sys, "argv", argv
            ), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(slack_print.main(), 0)
            fetch_channels.assert_not_called()
            self.assertIn("#C2PROD", output.read_text())

    def test_whole_thread_without_end_uses_membership_regardless_of_time(self):
        messages = [
            {"ts": "20.000001", "text": "parent"},
            {"ts": "10.000001", "thread_ts": "20.000001", "text": "earlier timestamp"},
            {"ts": "9999999999.000001", "thread_ts": "20.000001", "text": "late reply"},
            {"ts": "21.000001", "text": "other parent"},
            {"ts": "22.000001", "thread_ts": "21.000001", "text": "other reply"},
        ]
        selected = slack_print.select_messages(messages, "20.000001", None, True)
        self.assertEqual([message["text"] for message in selected],
                         ["parent", "earlier timestamp", "late reply"])
        capped = slack_print.select_messages(messages, "20.000001", "30.000001", True)
        self.assertEqual([message["text"] for message in capped], ["parent"])

    def test_single_thread_excludes_other_top_level_posts_and_threads(self):
        messages = [
            {"ts": "1712345678.000001", "user": "U1", "text": "wanted parent"},
            {"ts": "1712345679.000001", "thread_ts": "1712345678.000001", "user": "U2", "text": "wanted reply"},
            {"ts": "1712345680.000001", "user": "U3", "text": "other parent"},
            {"ts": "1712345681.000001", "thread_ts": "1712345680.000001", "user": "U4", "text": "other reply"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            count = slack_print.make_document(
                messages, "1712345678.000001", None, root, output, slack_print.dt.timezone.utc,
                False, "html", None, None, None, True,
            )
            page = output.read_text()
            self.assertEqual(count, 2)
            self.assertIn("wanted parent", page)
            self.assertIn("wanted reply", page)
            self.assertNotIn("other parent", page)
            self.assertNotIn("other reply", page)

    def test_missing_start_bound_warns(self):
        messages = [{"ts": "1712345679.000001", "text": "later"}]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            slack_print.warn_missing_bounds(messages, "1712345678.000001", None)
        self.assertIn("requested start message 1712345678.000001 is absent", stderr.getvalue())

    def test_missing_end_bound_warns_but_present_bounds_do_not(self):
        messages = [{"ts": "1712345678.000001", "text": "start"}]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            slack_print.warn_missing_bounds(messages, "1712345678.000001", "1712345679.000001")
        warning = stderr.getvalue()
        self.assertNotIn("requested start", warning)
        self.assertIn("requested end message 1712345679.000001 is absent", warning)

    def test_attribution_can_be_disabled(self):
        messages = [{"ts": "1712345678.000001", "user": "U1", "text": "message"}]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, output, slack_print.dt.timezone.utc,
                attribution=False,
            )
            page = output.read_text()
            self.assertNotIn("Created with", page)
            self.assertNotIn('<meta name="generator"', page)
            self.assertIn('<meta name="author" content="Slack Print">', page)
            self.assertIn('<meta name="description" content="Slack">', page)
            self.assertIn('<meta name="dcterms.created"', page)

    def test_timestamp_links_to_slack_but_header_does_not(self):
        messages = [{"ts": "1712345678.000001", "user": "U1", "text": "message"}]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "index.html"
            url = "https://example.slack.com/archives/C1/p1712345678000001"
            slack_print.make_document(
                messages, "1712345678.000001", None, root, output, slack_print.dt.timezone.utc,
                conversation_label="general", channel_id="C1", header_url=url,
            )
            page = output.read_text()
            self.assertIn(f'<h1>Slack: <a href="{url}">#general</a></h1>', page)
            self.assertIn(f'<a class="post-time" href="{url}">', page)
            self.assertNotIn("Slack ↗", page)

    def test_no_post_links_covers_posts_replies_and_orphans(self):
        messages = [
            {"ts": "1712345678.000001", "user": "U1", "text": "parent"},
            {"ts": "1712345679.000001", "thread_ts": "1712345678.000001", "text": "reply"},
            {"ts": "1712345680.000001", "thread_ts": "1712345670.000001", "text": "orphan"},
        ]
        url = "https://example.slack.com/archives/C1/p1712345678000001"
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for fmt, profile in (("markdown", "html"), ("html", "html"),
                                 ("html", "weasyprint"), ("html", "wkhtmltopdf")):
                for header_url in (None, url):
                    with self.subTest(format=fmt, profile=profile, url=header_url):
                        output = root / "document"
                        slack_print.make_document(
                            messages, messages[0]["ts"], None, root, output,
                            slack_print.dt.timezone.utc, include_attachments=False,
                            output_format=fmt, style_profile=profile, channel_id="C1",
                            conversation_label="general",
                            header_url=header_url, post_links=False,
                        )
                        page = output.read_text()
                        if fmt == "html":
                            self.assertEqual(page.count('<strong class="post-time"><time'), 3)
                            self.assertNotIn('<a class="post-time"', page)
                            self.assertIn('<h1>Slack: #general</h1>', page)
                        else:
                            self.assertEqual(page.count("**2024-04-05 "), 3)
                            self.assertNotIn("**[2024-04-05 ", page)
                            self.assertIn("# Slack: #general", page)
                        self.assertNotIn("https://example.slack.com", page)
                        self.assertNotIn('href="#p', page)
                        self.assertNotIn('](#p', page)

    def test_preview_and_post_link_flags_are_independent(self):
        message = {
            "ts": "1712345678.000001", "text": "<https://example.com>",
            "attachments": [{"title": "Preview title", "title_link": "https://example.com"}],
        }
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "messages.json"
            source.write_text(json.dumps([message]))
            for fmt in ("html", "markdown"):
                for preview_flag in (None, "-V", "--no-previews"):
                    for post_flag in (None, "-L", "--no-post-links"):
                        with self.subTest(format=fmt, preview=preview_flag, post=post_flag):
                            output = io.StringIO()
                            argv = [
                                "slack_print.py", message["ts"], "-i", str(source),
                                "-o", "-", "-A", "-q", "-f", fmt,
                                *([preview_flag] if preview_flag else []),
                                *([post_flag] if post_flag else []),
                            ]
                            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(
                                output
                            ), contextlib.redirect_stderr(io.StringIO()):
                                self.assertEqual(slack_print.main(), 0)
                            page = output.getvalue()
                            self.assertEqual("Preview title" in page, preview_flag is None)
                            link_marker = '<a class="post-time"' if fmt == "html" else '**[2024-04-05 '
                            self.assertEqual(link_marker in page, post_flag is None)
                            self.assertIn("https://example.com", page)

    def test_complete_reply_wins_over_stub(self):
        value = {
            "messages": [
                {"ts": "1712345678.000001", "text": "parent", "user": "U1", "replies": [{"ts": "1712345679.000001", "user": "U2"}]},
                {"ts": "1712345679.000001", "thread_ts": "1712345678.000001", "text": "full reply", "user": "U2"},
            ]
        }
        messages = {item["ts"]: item for item in slack_print.collect_messages(value)}
        self.assertEqual(messages["1712345679.000001"]["text"], "full reply")

    def test_reply_stub_without_full_message_is_not_a_phantom_post(self):
        value = {
            "messages": [{
                "ts": "1712345678.000001", "text": "parent", "user": "U1",
                "replies": [{"ts": "1712345679.000001", "user": "U2"}],
            }]
        }
        messages = slack_print.collect_messages(value)
        self.assertEqual([message["ts"] for message in messages], ["1712345678.000001"])

    def test_no_attachments_makes_no_assets_directory(self):
        messages = [{"ts": "1712345678.123456", "user": "U1", "text": "text", "files": [{"name": "x.png"}]}]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            slack_print.make_document(
                messages, "1712345678.123456", None, root, root / "index.html", slack_print.dt.timezone.utc, False
            )
            self.assertFalse((root / "index-files").exists())

    def test_custom_emoji_can_be_disabled_while_attachments_stay_enabled(self):
        messages = [{
            "ts": "1712345678.123456",
            "user": "U1",
            "text": "ship :party_parrot:",
            "files": [{"name": "note.txt"}],
        }]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "custom-emoji" / "emojis"
            source.mkdir(parents=True)
            (source / "party_parrot.gif").write_bytes(b"GIF89a")
            slack_print.make_document(
                messages, "1712345678.123456", None, root, root / "index.html",
                slack_print.dt.timezone.utc, True, include_custom_emoji=False,
            )
            page = (root / "index.html").read_text()
            self.assertIn("<code>:party_parrot:</code>", page)
            self.assertFalse((root / "index-files" / "emoji").exists())

    def test_attachment_uses_output_specific_assets_directory(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            attachment = root / "image.png"
            attachment.write_bytes(b"png")
            messages = [{
                "ts": "1712345678.123456", "text": "file",
                "files": [{"name": "image.png", "local_path": str(attachment)}],
            }]
            output = root / "foo.html"
            slack_print.make_document(
                messages, "1712345678.123456", None, root, output, slack_print.dt.timezone.utc
            )
            self.assertEqual((root / "foo-files" / "image.png").read_bytes(), b"png")
            self.assertIn('src="foo-files/image.png"', output.read_text())

    def test_linkable_file_detection_respects_range(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            attachment = root / "note.txt"
            attachment.write_text("note")
            messages = [{
                "ts": "1712345680.000001", "text": "later",
                "files": [{"local_path": str(attachment)}],
            }]
            self.assertFalse(slack_print.has_linkable_files(
                messages, root, "1712345678.000001", "1712345679.000001"
            ))
            self.assertTrue(slack_print.has_linkable_files(messages, root, "1712345678.000001", None))

    def test_linkable_file_detection_includes_late_thread_attachments(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            attachment = root / "note.txt"
            attachment.write_text("note")
            messages = [
                {"ts": "1712345678.000001", "text": "parent"},
                {"ts": "1712345680.000001", "thread_ts": "1712345678.000001",
                 "files": [{"local_path": str(attachment)}]},
            ]
            self.assertTrue(slack_print.has_linkable_files(
                messages, root, "1712345678.000001", "1712345679.000001"
            ))
            self.assertFalse(slack_print.has_linkable_files(
                messages, root, "1712345678.000001", "1712345679.000001", True
            ))

    def test_stdout_rejects_local_emoji_in_html_and_markdown(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            emoji_root = root / "custom-emoji" / "emojis"
            emoji_root.mkdir(parents=True)
            (emoji_root / "party.gif").write_bytes(b"image")
            (root / "custom-emoji" / "index.json").write_text(json.dumps({"alias": "alias:party"}))
            (root / "messages.json").write_text(json.dumps([
                {"ts": "1712345678.000001", "text": ":alias:"},
            ]))
            for output_format in ("html", "markdown"):
                with self.subTest(output_format=output_format):
                    argv = ["slack_print.py", "C1:1712345678.000001", "-i", str(root),
                            "-o", "-", "-f", output_format, "-q"]
                    stderr = io.StringIO()
                    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as error:
                            slack_print.main()
                    self.assertEqual(error.exception.code, 2)
                    self.assertIn("stdout cannot include local attachment links", stderr.getvalue())
            self.assertFalse(slack_print.has_linkable_files(
                [{"ts": "1712345678.000001", "text": ":alias:"}], root,
                "1712345678.000001", None, include_custom_emoji=False,
            ))

    def test_markdown_thread_and_anchor(self):
        messages = [
            {"ts": "1712345678.123456", "user": "U1", "text": "*parent*"},
            {"ts": "1712345679.000001", "thread_ts": "1712345678.123456", "user": "U2", "text": "reply"},
        ]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            output = root / "document.md"
            slack_print.make_document(
                messages, "1712345678.123456", None, root, output, slack_print.dt.timezone.utc, False, "markdown",
                None, "general", ["U1", "U2"]
            )
            page = output.read_text()
            self.assertIn('<a id="p1712345678123456"></a>', page)
            self.assertIn('[2024-04-05 19:34:38 UTC](#p1712345678123456)', page)
            self.assertNotIn('[p1712345678123456]', page)
            self.assertIn("**parent**", page)
            self.assertIn("Replies:", page)
            self.assertIn("- <a id=", page)
            self.assertIn("# Slack: #general", page)
            self.assertIn("From 2024-04-05 19:34:38 UTC through 2024-04-05 19:34:39 UTC", page)
            self.assertIn("**Participants:** U1, U2", page)
            self.assertIn("2024-04-05 19:34:39 UTC", page)
            self.assertIn("Created with Slack Print by John K. Hinsdale of Princeton Junction, NJ USA", page)


if __name__ == "__main__":
    unittest.main()
