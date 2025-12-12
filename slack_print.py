#!/usr/bin/env python3
"""Print part of one Slack conversation using slackdump output."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


SLACK_REF = re.compile(r"/archives/([A-Z0-9]+)/p(\d+)")
TS_REF = re.compile(r"^(?:p)?(\d{10})(\d{6})$")
EMOJI_ALIAS = re.compile(r"(?<![A-Za-z0-9_`]):([A-Za-z0-9_+-]+):(?![A-Za-z0-9_`])")
CHANNEL_MENTION = re.compile(r"<#([CG][A-Z0-9]+)(?:\|[^>]+)?>")
STANDARD_EMOJI = {
    "+1": "👍", "thumbsup": "👍", "-1": "👎", "thumbsdown": "👎",
    "heart": "❤️", "red_heart": "❤️", "orange_heart": "🧡", "yellow_heart": "💛",
    "green_heart": "💚", "blue_heart": "💙", "purple_heart": "💜", "broken_heart": "💔",
    "heart_hands": "🫶",
    "smile": "😄", "grinning": "😀", "joy": "😂", "laughing": "😆", "blush": "😊",
    "slightly_smiling_face": "🙂", "wink": "😉", "heart_eyes": "😍", "thinking_face": "🤔",
    "cry": "😢", "sob": "😭", "angry": "😠", "rage": "😡", "scream": "😱",
    "tada": "🎉", "fire": "🔥", "rocket": "🚀", "eyes": "👀", "wave": "👋",
    "partying_face": "🥳", "clinking_glasses": "🥂", "champagne": "🍾", "birthday": "🎂",
    "cake": "🎂", "croissant": "🥐", "eagle": "🦅", "us": "🇺🇸", "flag-us": "🇺🇸",
    "b": "🅱️",
    "goat": "🐐", "female_superhero": "🦸‍♀️", "coffee": "☕", "hammer_and_wrench": "🛠️",
    "droplet": "💧",
    "clap": "👏", "raised_hands": "🙌", "pray": "🙏", "muscle": "💪", "ok_hand": "👌",
    "white_check_mark": "✅", "heavy_check_mark": "✔️", "x": "❌", "warning": "⚠️",
    "information_source": "ℹ️", "question": "❓", "exclamation": "❗", "star": "⭐",
    "100": "💯", "bulb": "💡", "memo": "📝", "link": "🔗", "lock": "🔒",
}
SKIN_TONES = {"2": "🏻", "3": "🏼", "4": "🏽", "5": "🏾", "6": "🏿"}
EMOJI_CACHE_ROOT = Path("/tmp/slack-emoji")
STANDARD_EMOJI_DATA_URL = "https://cdn.jsdelivr.net/gh/iamcal/emoji-data@master/emoji.json"
TWEMOJI_SVG_BASE = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@17.0.3/assets/svg"
TWEMOJI_PNG_BASE = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@17.0.3/assets/72x72"
PDF_AUTHOR = "Slack Print"
ATTRIBUTION = "Created with Slack Print by John K. Hinsdale of Princeton Junction, NJ USA"
PDF_APPLICATION = "Slack Print by John K. Hinsdale"
BASE_CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1d1c1d}
article{padding:.7rem 0;border-top:1px solid #ddd} header{font-size:.82rem;color:#666}.post-time{color:inherit}
article.user-highlight{background-color:#e8f4ff;print-color-adjust:exact;-webkit-print-color-adjust:exact}
.author{font-size:1rem;font-weight:700;color:#333;margin-left:.5rem}.message-meta{margin-left:.5rem;color:#777}.deleted-marker{color:#777;font-style:italic}
.body{margin:.3rem 0;white-space:normal}.mention{color:#1264a3;background:#e8f5fa;text-decoration:none}
.thread{list-style:none;margin:.4rem 0 .5rem 1.2rem;padding-left:1rem;border-left:3px solid #ddd}.thread>li{position:relative;margin:.15rem 0}.thread>li::before{content:"";position:absolute;left:-.72rem;top:.85rem;width:.35rem;height:.35rem;border-radius:50%;background:#777}.thread article{border:0;padding:.2rem 0}
img{display:block;max-width:min(100%,700px);max-height:700px;margin:.6rem 0}.emoji{display:inline-block;width:1.25em;height:1.25em;max-width:1.25em;max-height:1.25em;object-fit:contain;margin:0 .08em;vertical-align:-.25em}.reactions{display:flex;flex-wrap:wrap;gap:.3rem;margin:.4rem 0}.reaction,.reaction-type{border:1px solid #ccc;border-radius:1rem;padding:.1rem .5rem;background:#f7f7f7}.reactions.extended{display:flex;gap:.2rem .5rem}.reactions.extended .reaction{display:inline-flex;align-items:center;gap:.25rem;border:0;border-radius:0;padding:0;background:none}.reactions.extended .reaction-type{display:inline-block}.reactions.stacked{display:block}.reactions.stacked .reaction{display:block;margin:0 0 .15rem 0}.reactor-names{font-size:.92em;overflow-wrap:anywhere}.file{display:block;margin:.4rem 0}code{background:#eee;padding:.1rem .25rem;overflow-wrap:anywhere}
blockquote{margin:.5rem 0;padding:.2rem .8rem;border-left:4px solid #bbb;color:#555}blockquote+blockquote{margin-top:-.5rem}blockquote:empty{display:none}blockquote>ol,blockquote>ul{margin:0;padding-left:1.3rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:.6rem}pre code{background:none;padding:0}
.link-preview{position:relative;margin:.6rem 0;padding:.55rem .75rem;border:1px solid #ddd;border-left:4px solid #888;border-radius:.25rem;min-height:1.5rem}.preview-source{font-size:.8rem;color:#666}.preview-title{display:block;font-weight:650}.preview-text,.preview-field{margin-top:.25rem}.preview-image{max-width:180px;max-height:120px;margin:.5rem 0 0}"""
PRINT_CSS = """@media print{
body{font-size:11pt;max-width:none;margin:0;padding:0}
.thread,article{break-inside:auto}
article>header{break-after:avoid-page}
.body{height:auto;overflow:visible;overflow-wrap:anywhere;word-break:break-word;orphans:3;widows:3}
img{max-width:100%;max-height:4in;object-fit:contain;break-inside:avoid-page}
}"""
PDF_CONVERTER_CSS = {
    "wkhtmltopdf": """.reaction .emoji,.reaction-type .emoji{width:18px;height:18px;min-width:18px;min-height:18px;max-width:18px;max-height:18px;vertical-align:-4px}
.reaction .emoji-bg,.reaction-type .emoji-bg{display:inline-block;background-repeat:no-repeat;background-position:center;background-size:18px 18px}
.reactions>.reaction{margin:0 .45rem .3rem 0}.reactions.extended .reaction{margin:0 .5rem .15rem 0}.reactions.extended .reaction-type{margin-right:.25rem}""",
    "weasyprint": """@page{size:Letter;margin:.45in .4in}
.reactions{display:block}.reactions>.reaction{display:inline-block;margin:0 .3rem .3rem 0;border:0;background:#f7f7f7;border-radius:1rem}.reactions.extended{display:block}.reactions.extended .reaction{display:inline-block;margin:0 .5rem .15rem 0;padding:0;border-radius:0;background:none;vertical-align:top}.reactions.extended.stacked .reaction{display:block}.reactions.extended .reaction-type{display:inline-block;border:0;background:#f7f7f7;border-radius:1rem}""",
}
PDF_CONVERTERS = ("weasyprint", "wkhtmltopdf")


def html_stylesheet(style_profile: str = "html") -> str:
    """Return renderer-neutral CSS plus optional converter-specific fallbacks."""
    parts = [BASE_CSS, PRINT_CSS]
    if style_profile in PDF_CONVERTER_CSS:
        parts.append(PDF_CONVERTER_CSS[style_profile])
    return "\n".join(parts)


class ErrorLastArgumentParser(argparse.ArgumentParser):
    """Show an error before the usage hint."""

    def error(self, message: str) -> None:
        self._print_message(f"{self.prog}: error: {message}\n\n", sys.stderr)
        self.print_usage(sys.stderr)
        self.exit(2)


def calendar_reference(value: str | None) -> bool:
    """Calendar prefixes are 4–14 digits; Slack post IDs stay 16 digits."""
    return bool(value and re.fullmatch(r"[0-9]{4,14}", value.rsplit(":", 1)[-1]))


def parse_ref(value: str, default_channel: str | None = None) -> tuple[str | None, str]:
    """Read a URL, CHANNEL:time, or time (UTC calendar prefix or Slack ts)."""
    match = SLACK_REF.search(value)
    if match:
        raw = match.group(2)
        return match.group(1), f"{raw[:10]}.{raw[10:16]}"
    channel = default_channel
    if ":" in value:
        channel, value = value.rsplit(":", 1)
        if not channel or not re.fullmatch(r"(?:[A-Z0-9]+|[@#][^:]+|[A-Za-z][^:]*)", channel):
            raise ValueError(f"cannot read conversation: {channel}")
    match = TS_REF.fullmatch(value)
    if match:
        return channel, f"{match.group(1)}.{match.group(2)}"
    if re.fullmatch(r"[0-9]{10}\.[0-9]{1,6}", value):
        return channel, value
    if calendar_reference(value):
        # Month/day default to 01; time digits default to zero. Partial fields
        # overwrite the leading digits of that valid beginning-of-year date.
        padded = value + "00000101000000"[len(value):]
        try:
            instant = dt.datetime(
                int(padded[:4]), int(padded[4:6]), int(padded[6:8]),
                int(padded[8:10]), int(padded[10:12]), int(padded[12:14]),
                tzinfo=dt.timezone.utc,
            )
        except ValueError as exc:
            raise ValueError(f"invalid UTC date prefix {value}: {exc}") from exc
        epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        return channel, f"{(instant - epoch).days * 86400 + (instant - epoch).seconds}.000000"
    raise ValueError(f"cannot read post reference: {value}")


def named_conversation(channel: str | None) -> bool:
    return bool(channel and not re.fullmatch(r"[CDG][A-Z0-9]+", channel))


def resolve_conversation(channel: str, values: list[Any]) -> str:
    """Resolve a public #channel or an existing one-to-one DM by user name."""
    records: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            records.append(node)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(values)
    if channel.startswith("#"):
        wanted = channel[1:].casefold()
        matches = {
            record["id"] for record in records
            if isinstance(record.get("id"), str)
            and record["id"].startswith("C")
            and not record.get("is_private") and not record.get("is_im")
            and not record.get("is_mpim")
            and str(record.get("name", "")).casefold() == wanted
        }
    else:
        users = highlighted_user_ids([
            record for record in records
            if isinstance(record.get("id"), str)
            and re.fullmatch(r"[UW][A-Z0-9]+", record["id"])
        ], channel)
        if len(users) != 1:
            reason = "ambiguous user" if users else "user not found"
            raise ValueError(f"{reason}: {channel}; use an exact Slack name or @USER_ID")
        user = next(iter(users))
        matches = {
            record["id"] for record in records
            if isinstance(record.get("id"), str) and record["id"].startswith("D")
            and record.get("user") == user
        }
    if len(matches) != 1:
        reason = "ambiguous conversation" if matches else "conversation not found"
        raise ValueError(f"{reason}: {channel}; supply its channel ID instead")
    return next(iter(matches))


def ts_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def utc_arg(ts: str, offset: int = 0) -> str:
    instant = dt.datetime.fromtimestamp(float(ts) + offset, tz=dt.timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S")


def workspace_hint(reference: str, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    parsed = urlparse(reference)
    if parsed.hostname and parsed.hostname.endswith(".slack.com"):
        return f"https://{parsed.hostname}"
    return None


def workspace_from_url(reference: str | None) -> str | None:
    if not reference:
        return None
    parsed = urlparse(reference)
    hostname = parsed.hostname or ""
    if hostname.endswith(".slack.com"):
        return hostname.removesuffix(".slack.com")
    return None


def workspace_name(value: str) -> str:
    return workspace_from_url(value if "://" in value else f"https://{value}") or value


def slack_message_url(
    reference: str, workspace: str | None, channel: str | None, timestamp: str
) -> str | None:
    """Return a canonical Slack message URL when its workspace domain is known."""
    candidates = (reference, workspace or "")
    hostname = None
    for candidate in candidates:
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        if parsed.hostname and parsed.hostname.endswith(".slack.com"):
            hostname = parsed.hostname
            break
    if not hostname or not channel:
        return None
    return f"https://{hostname}/archives/{channel}/{post_id(timestamp)}"


def related_slack_message_url(header_url: str | None, channel: str | None, timestamp: str) -> str | None:
    if not header_url or not channel:
        return None
    parsed = urlparse(header_url)
    if not parsed.hostname or not parsed.hostname.endswith(".slack.com"):
        return None
    return f"https://{parsed.hostname}/archives/{channel}/{post_id(timestamp)}"


def related_slack_channel_url(header_url: str | None, channel: str | None) -> str | None:
    if not header_url or not channel:
        return None
    parsed = urlparse(header_url)
    if not parsed.hostname or not parsed.hostname.endswith(".slack.com"):
        return None
    return f"https://{parsed.hostname}/archives/{channel}"


def related_slack_user_url(header_url: str | None, user_id: str | None) -> str | None:
    if not header_url or not user_id:
        return None
    parsed = urlparse(header_url)
    if not parsed.hostname or not parsed.hostname.endswith(".slack.com"):
        return None
    return f"https://{parsed.hostname}/team/{user_id}"


def api_config_flags(api_config: Path | None) -> list[str]:
    return ["-api-config", str(api_config.resolve())] if api_config else []


def slackdump_available() -> bool:
    return shutil.which("slackdump") is not None


def wkhtmltopdf_available() -> bool:
    return shutil.which("wkhtmltopdf") is not None


def weasyprint_available() -> bool:
    return shutil.which("weasyprint") is not None


def available_pdf_converters() -> list[str]:
    converters = []
    if weasyprint_available():
        converters.append("weasyprint")
    if wkhtmltopdf_available():
        converters.append("wkhtmltopdf")
    return converters


def default_pdf_converter() -> str | None:
    converters = available_pdf_converters()
    return converters[0] if converters else None


def resolve_pdf_converter(requested: str) -> str | None:
    if requested == "auto":
        return default_pdf_converter()
    return requested if requested in available_pdf_converters() else None


def wkhtmltopdf_command(
    source: Path, destination: str, verbose: bool, very_verbose: bool = False
) -> list[str]:
    command = ["wkhtmltopdf"]
    if not verbose:
        command.append("--quiet")
    if very_verbose:
        command += ["--log-level", "info"]
    command.extend([
        "--page-size", "Letter",
        "--margin-left", "0.4in", "--margin-right", "0.4in",
        "--margin-top", "0.45in", "--margin-bottom", "0.45in",
        "--load-error-handling", "ignore", "--load-media-error-handling", "ignore",
        "--disable-smart-shrinking", "--enable-local-file-access",
        str(source), destination,
    ])
    return command


def weasyprint_command(
    source: Path, destination: str, verbose: bool, very_verbose: bool = False
) -> list[str]:
    command = ["weasyprint"]
    if not verbose:
        command.append("--quiet")
    if very_verbose:
        command.append("--verbose")
    command.extend([
        "--custom-metadata",
        "--media-type", "print",
        "--base-url", str(source.parent.resolve()),
        str(source), destination,
    ])
    return command


def pdf_command(
    converter: str, source: Path, destination: str, verbose: bool, very_verbose: bool = False
) -> list[str]:
    if converter == "weasyprint":
        return weasyprint_command(source, destination, verbose, very_verbose)
    if converter == "wkhtmltopdf":
        return wkhtmltopdf_command(source, destination, verbose, very_verbose)
    raise ValueError(f"unknown PDF converter: {converter}")


def pdf_output_options(verbose: bool, to_stdout: bool = False) -> dict[str, Any]:
    """Hide converter chatter unless verbose output was requested."""
    if verbose:
        return {}
    if to_stdout:
        return {"stderr": subprocess.PIPE}
    return {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}


def wkhtmltopdf_output_options(verbose: bool) -> dict[str, Any]:
    return pdf_output_options(verbose)


def progress(message: str, quiet: bool = False) -> None:
    """Print normal progress to stderr unless quiet mode suppresses it."""
    if not quiet:
        print(message, file=sys.stderr)


def authenticate(hint: str | None) -> None:
    """Run slackdump's browser login. Slackdump owns encrypted credential storage."""
    workspace = hint
    if not workspace:
        workspace = input("Slack workspace name or URL (example.slack.com): ").strip()
    if not workspace:
        raise RuntimeError("Slack workspace is required for login")
    print("Slackdump will open a browser. Log in there. Return here when browser closes.", file=sys.stderr)
    command = ["slackdump", "workspace", "new", workspace]
    subprocess.run(command, check=True)


def ensure_auth(hint: str | None, force: bool) -> str | None:
    """Check login and announce implicit use of Slackdump’s current workspace."""
    if force and hint:
        authenticate(hint)
        return hint
    check = subprocess.run(
        ["slackdump", "workspace", "list", "-b"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check.returncode:
        raise RuntimeError("could not list saved Slack workspaces; run slackdump workspace list for details")
    workspaces = list(dict.fromkeys(
        line.strip().removeprefix("*").strip()
        for line in check.stdout.splitlines() if line.strip().removeprefix("*").strip()
    ))
    selected = hint
    if not selected and workspaces:
        current = [line.strip()[1:].strip() for line in check.stdout.splitlines()
                   if line.strip().startswith("*")]
        if len(current) == 1 and current[0]:
            selected = current[0]
        elif len(workspaces) == 1:
            selected = workspaces[0]
        else:
            raise RuntimeError("cannot identify default Slack workspace; select one with slackdump workspace select NAME or pass -w NAME")
        print(f"USING DEFAULT WORKSPACE: {selected}", file=sys.stderr)
    if force:
        authenticate(selected)
        return selected
    if workspaces:
        return selected
    print("No saved Slack login found.", file=sys.stderr)
    if not sys.stdin.isatty():
        raise RuntimeError("run interactively once with --login to save Slack authentication")
    answer = input("Log in to Slack now? [Y/n] ").strip().lower()
    if answer not in ("", "y", "yes"):
        raise RuntimeError("Slack login required")
    authenticate(selected)
    return selected


def run_slackdump(command: list[str], verbose: bool, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run slackdump quietly, but reveal its diagnostics when it fails."""
    if verbose:
        return subprocess.run(command, check=True, **kwargs)
    try:
        return subprocess.run(
            command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        )
    except subprocess.CalledProcessError as exc:
        diagnostics = "\n".join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if diagnostics:
            print(diagnostics, file=sys.stderr)
        raise


def run_slackdump_with_progress(
    command: list[str],
    verbose: bool,
    quiet: bool,
    wait_label: str,
    advisory_after: int | None = None,
    advisory: str | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a non-dump slackdump command with periodic waiting feedback."""
    if verbose:
        return subprocess.run(command, check=True, **kwargs)
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    started = time.monotonic()
    last_wait_message = started
    advisory_printed = False
    while process.poll() is None:
        now = time.monotonic()
        if not quiet and now - last_wait_message >= 15:
            elapsed = int(now - started)
            print(f"... still {wait_label} after {elapsed}s ...", file=sys.stderr)
            last_wait_message = now
            if advisory_after is not None and advisory and not advisory_printed and elapsed >= advisory_after:
                print(advisory, file=sys.stderr)
                advisory_printed = True
        time.sleep(1)
    stdout, stderr = process.communicate()
    if process.returncode:
        exc = subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        diagnostics = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
        if diagnostics:
            print(diagnostics, file=sys.stderr)
        raise exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def rate_limit_message(line: str) -> str | None:
    if "got rate limited" not in line and "slack rate limit exceeded" not in line:
        return None
    match = re.search(r"retry_after=([^\s]+)|retry after ([0-9]+s)", line)
    wait = next((group for group in (match.groups() if match else ()) if group), None)
    return f"Slackdump is rate limited; waiting {wait}..." if wait else "Slackdump is rate limited; waiting..."


def monitor_slackdump_log(path: Path, quiet: bool, state: dict[str, int | str | None]) -> None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(int(state.get("position") or 0))
            for line in handle:
                message = rate_limit_message(line)
                if not message:
                    continue
                count = int(state.get("rate_limit_count") or 0) + 1
                state["rate_limit_count"] = count
                if message != state.get("last_rate_limit_message"):
                    print(message, file=sys.stderr)
                    state["last_rate_limit_message"] = message
                if count == 2:
                    print(
                        "Repeated Slack rate limits detected; continuing to wait.",
                        file=sys.stderr,
                    )
            state["position"] = handle.tell()
    except FileNotFoundError:
        return


def slackdump_log_command(command: list[str], log_path: Path) -> list[str]:
    return [*command[:-1], "-log", str(log_path), command[-1]]


def log_tail(path: Path, lines: int = 20) -> str:
    try:
        values = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(values[-lines:])


def valid_json_file(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)
        return True
    except (OSError, json.JSONDecodeError):
        return False


def finish_process(process: subprocess.Popen[str], timeout: float = 5) -> tuple[str | None, str | None]:
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


def run_slackdump_dump(
    command: list[str],
    verbose: bool,
    log_path: Path,
    quiet: bool,
    early_success_path: Path | None = None,
    wait_label: str = "Slackdump",
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run slackdump dump with a log file and surface concise rate-limit status."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = slackdump_log_command(command, log_path)
    if verbose:
        process = subprocess.Popen(command, **kwargs)
    else:
        process = subprocess.Popen(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        )
    state: dict[str, int | str | None] = {"position": 0, "rate_limit_count": 0, "last_rate_limit_message": None}
    started = time.monotonic()
    last_wait_message = started
    while process.poll() is None:
        monitor_slackdump_log(log_path, quiet, state)
        if early_success_path and valid_json_file(early_success_path):
            process.terminate()
            stdout, stderr = finish_process(process)
            monitor_slackdump_log(log_path, quiet, state)
            return subprocess.CompletedProcess(command, 0, stdout, stderr)
        now = time.monotonic()
        if not quiet and now - last_wait_message >= 15:
            elapsed = int(now - started)
            print(f"... still {wait_label} after {elapsed}s ...", file=sys.stderr)
            last_wait_message = now
        time.sleep(1)
    stdout, stderr = process.communicate()
    monitor_slackdump_log(log_path, quiet, state)
    if process.returncode:
        exc = subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        if not verbose:
            diagnostics = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
            tail = log_tail(log_path)
            if tail:
                diagnostics = "\n".join(part for part in (diagnostics, tail) if part)
            if diagnostics:
                print(diagnostics, file=sys.stderr)
        raise exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def fetch_user_directory(
    root: Path, workspace: str | None, verbose: bool = False,
    very_verbose: bool = False, quiet: bool = False,
) -> None:
    """Save workspace user profiles beside the message dump for name resolution."""
    root.mkdir(parents=True, exist_ok=True)
    command = [
        "slackdump", "list", "users", *([] if very_verbose else ["-q"]),
        "-y", "-format", "JSON",
    ]
    if workspace:
        command += ["-workspace", workspace]
    if very_verbose:
        command.append("-v")
    try:
        # slackdump 4.4 names this file itself (users-TEAM.json). Run in the
        # fresh dump directory so it cannot collide with an earlier run.
        run_slackdump_with_progress(
            command,
            verbose,
            quiet,
            "fetching Slack user names",
            advisory_after=60,
            advisory="Note: use -I/--raw-user-ids to skip user-name lookup and show raw Slack user IDs.",
            cwd=root,
        )
    except subprocess.CalledProcessError as exc:
        print(f"warning: could not fetch user names (exit status {exc.returncode}); IDs remain visible", file=sys.stderr)


def fetch_channel_directory(
    root: Path, workspace: str | None, verbose: bool = False,
    very_verbose: bool = False, quiet: bool = False,
    channel_types: str | None = None,
) -> None:
    """Save conversation metadata, optionally restricted to lookup types."""
    root.mkdir(parents=True, exist_ok=True)
    command = [
        "slackdump", "list", "channels", *([] if very_verbose else ["-q"]),
        "-y", "-format", "JSON",
    ]
    if channel_types:
        command += ["-chan-types", channel_types, "-no-chan-cache"]
    if workspace:
        command += ["-workspace", workspace]
    if very_verbose:
        command.append("-v")
    try:
        label = "fetching Slack DM channels" if channel_types == "im" else "fetching Slack channel names"
        run_slackdump_with_progress(command, verbose, quiet, label, cwd=root)
    except subprocess.CalledProcessError as exc:
        print(f"warning: could not fetch channel names (exit status {exc.returncode}); channel IDs remain visible", file=sys.stderr)


def fetch_custom_emoji(
    root: Path, workspace: str | None, verbose: bool = False, very_verbose: bool = False,
    quiet: bool = False,
) -> None:
    """Download workspace emoji metadata only; images are selected later."""
    command = ["slackdump", "emoji", "-o", str(root / "custom-emoji"), "-files=false"]
    if workspace:
        command += ["-workspace", workspace]
    if very_verbose:
        command.append("-v")
    try:
        run_slackdump_with_progress(command, verbose, quiet, "fetching Slack custom emoji list (image downloads have not started)")
    except subprocess.CalledProcessError as exc:
        print(f"warning: could not fetch custom emoji (exit status {exc.returncode}); aliases remain visible", file=sys.stderr)


def emoji_cache_directory(workspace: str | None) -> Path | None:
    """Resolve a workspace cache without reading Slackdump credentials."""
    if not workspace:
        try:
            result = subprocess.run(
                ["slackdump", "workspace", "list", "-b"], check=True,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            )
            workspace = next((line[1:].strip() for line in result.stdout.splitlines() if line.startswith("*")), None)
        except (OSError, subprocess.SubprocessError):
            return None
    if not workspace:
        return None
    name = workspace_name(workspace)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        return None
    return EMOJI_CACHE_ROOT / name


def emoji_image_suffix(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".png", ".gif", ".jpg", ".jpeg", ".webp", ".svg", ".avif"} else ".png"


def download_selected_emoji(
    root: Path, wanted: set[str], quiet: bool = False, cache_dir: Path | None = None,
) -> None:
    """Download only referenced images, resolving aliases from Slackdump's index."""
    if not wanted:
        return
    emoji_root = root / "custom-emoji"
    try:
        entries = json.loads((emoji_root / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(entries, dict):
        return
    downloads: dict[str, str] = {}
    for name in sorted(wanted):
        seen: set[str] = set()
        while name not in seen:
            seen.add(name)
            value = entries.get(name)
            if not isinstance(value, str):
                break
            if value.startswith("alias:"):
                name = value[6:]
                continue
            if name in downloads or not re.fullmatch(r"[A-Za-z0-9_+-]+", name):
                break
            if urlparse(value).scheme not in {"https", "http"}:
                break
            downloads[name] = value
            break

    cached_paths: dict[str, Path] = {}
    reused = 0
    if cache_dir is not None and downloads:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name, url in list(downloads.items()):
                # A changed URL gets a new key; stale images cannot override the fresh index.
                digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
                cached = cache_dir / f"{name}-{digest}{emoji_image_suffix(url)}"
                cached_paths[name] = cached
                if cached.is_file() and cached.stat().st_size:
                    destination = emoji_root / "emojis" / (name + emoji_image_suffix(url))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cached, destination)
                    del downloads[name]
                    reused += 1
        except OSError as exc:
            print(f"warning: emoji cache unavailable: {exc}; continuing with downloads", file=sys.stderr)
            cached_paths.clear()
    if reused:
        progress(f"Reused {reused} cached emoji; {len(downloads)} to download.", quiet)

    started = time.monotonic()
    completed = failed = 0
    stopped = threading.Event()
    lock = threading.Lock()

    def report() -> None:
        elapsed = int(time.monotonic() - started)
        failures = f"; {failed} failed" if failed else ""
        progress(f"Downloaded {completed}/{len(downloads)} emoji after {elapsed} seconds{failures}.", quiet)

    def report_wait() -> None:
        while not stopped.wait(15):
            with lock:
                report()

    report()
    reporter = threading.Thread(target=report_wait, daemon=True)
    if not quiet and downloads:
        reporter.start()
    try:
        for name, value in downloads.items():
            destination = emoji_root / "emojis" / (name + emoji_image_suffix(value))
            try:
                with urllib.request.urlopen(value, timeout=20) as response:
                    data = response.read()
                if not data:
                    raise ValueError("empty image response")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            except (OSError, TimeoutError, ValueError) as exc:
                destination.unlink(missing_ok=True)
                with lock:
                    failed += 1
                    print(f"warning: could not fetch emoji {name}: {exc}; remote URL remains available", file=sys.stderr)
                    report()
            else:
                cached = cached_paths.get(name)
                if cached is not None:
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=cache_dir, prefix=".emoji-", delete=False) as handle:
                            temporary = Path(handle.name)
                            handle.write(data)
                        temporary.replace(cached)
                    except OSError as exc:
                        print(f"warning: could not cache emoji {name}: {exc}", file=sys.stderr)
                    finally:
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
                with lock:
                    completed += 1
                    report()
    finally:
        stopped.set()
        if reporter.is_alive():
            reporter.join()


def fetch_standard_emoji_data(root: Path) -> None:
    """Fetch the full standard colon-alias map into run-local temporary data."""
    destination = root / "custom-emoji" / "standard-emoji.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(STANDARD_EMOJI_DATA_URL, timeout=20) as response:
            destination.write_bytes(response.read())
    except (OSError, TimeoutError) as exc:
        print(f"warning: could not fetch standard emoji aliases: {exc}; built-in aliases remain available", file=sys.stderr)


def custom_emoji_assets(source_root: Path, assets: Path, wanted: set[str] | None = None) -> dict[str, str]:
    """Resolve wanted emoji from downloaded files and slackdump emoji JSON."""
    found: dict[str, str] = {}
    remote: dict[str, str] = {}
    aliases: dict[str, str] = {}
    emoji_root = source_root / "custom-emoji"
    if not emoji_root.exists():
        return found
    for metadata in emoji_root.rglob("*.json"):
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if isinstance(value, list):
            for entry in value:
                if not isinstance(entry, dict) or not isinstance(entry.get("unified"), str):
                    continue
                codepoints = entry["unified"].lower()
                if "-200d-" not in codepoints:
                    codepoints = codepoints.replace("-fe0f", "")
                url = f"{TWEMOJI_SVG_BASE}/{codepoints}.svg"
                short_names = entry.get("short_names") if isinstance(entry.get("short_names"), list) else []
                if isinstance(entry.get("short_name"), str):
                    short_names = [entry["short_name"], *short_names]
                for short_name in short_names:
                    remote.setdefault(str(short_name), url)
            continue
        entries = value.get("emoji") if isinstance(value, dict) and isinstance(value.get("emoji"), dict) else value
        if not isinstance(entries, dict):
            continue
        for key, entry in entries.items():
            name = str(key)
            if isinstance(entry, str):
                if entry.startswith("alias:"):
                    aliases[name] = entry[6:]
                elif entry.startswith(("https://", "http://")):
                    remote[name] = entry
            elif isinstance(entry, dict):
                url = entry.get("url")
                canonical = str(entry.get("name") or name)
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    remote[canonical] = url
                for alias in entry.get("aliases", []) if isinstance(entry.get("aliases"), list) else []:
                    aliases[str(alias)] = canonical
    target_root = assets / "emoji"
    file_wanted = set(wanted) if wanted is not None else None
    if file_wanted is not None:
        pending = list(file_wanted)
        while pending:
            target_name = aliases.get(pending.pop())
            if target_name and target_name not in file_wanted:
                file_wanted.add(target_name)
                pending.append(target_name)
    for source in emoji_root.rglob("*"):
        if not source.is_file() or source.suffix.lower() in {".json", ".txt"}:
            continue
        name = source.stem
        if file_wanted is not None and name not in file_wanted:
            continue
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / source.name
        if not target.exists():
            shutil.copy2(source, target)
        found.setdefault(name, f"{assets.name}/emoji/{target.name}")
    names = wanted if wanted is not None else set(remote) | set(aliases)
    def resolve(name: str, seen: set[str] | None = None) -> str | None:
        if name in found:
            return found[name]
        if name in remote:
            return remote[name]
        seen = seen or set()
        if name in seen or name not in aliases:
            return None
        seen.add(name)
        return resolve(aliases[name], seen)
    for name in names:
        resolved = resolve(name)
        if resolved:
            found[name] = resolved
    return found


def message_emoji_names(messages: list[dict[str, Any]]) -> set[str]:
    """Find custom emoji names referenced by message text or Block Kit."""
    names: set[str] = set()
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "emoji" and isinstance(node.get("name"), str):
                names.add(node["name"])
            if "count" in node and isinstance(node.get("name"), str):
                names.add(node["name"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            names.update(EMOJI_ALIAS.findall(node))
    walk(messages)
    return names


def message_channel_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Find Slack channel IDs that appear as visible mentions in message content."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "channel" and isinstance(node.get("channel_id"), str):
                channel_id = node["channel_id"]
                if re.fullmatch(r"[CG][A-Z0-9]+", channel_id):
                    found.add(channel_id)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.update(CHANNEL_MENTION.findall(node))

    walk(messages)
    return found


def post_id(ts: str) -> str:
    return "p" + ts.replace(".", "")


def load_json_files(root: Path) -> list[Any]:
    values: list[Any] = []
    for path in sorted(root.rglob("*.json")):
        try:
            values.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"warning: skip {path}: {exc}", file=sys.stderr)
    for path in sorted(root.rglob("*.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        values.append(json.loads(line))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"warning: skip {path}: {exc}", file=sys.stderr)
    return values


def debug_dump_json_path(enabled: bool, output: Path | None) -> Path | None:
    if not enabled:
        return None
    if output is None or str(output) == "-":
        return Path("slack-print-json-input.json")
    return output.with_name(f"{output.stem}-json-input.json")


def write_debug_json(values: list[Any], destination: Path, force: bool) -> None:
    """Write the JSON values used for rendering into one persistent debug file."""
    require_available_output(destination, force)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_zip_safely(zip_file: zipfile.ZipFile, destination: Path) -> None:
    """Extract a ZIP only when every member stays below destination."""
    destination = destination.resolve()
    for member in zip_file.infolist():
        # ZIP names use forward slashes. Treat backslashes as separators too,
        # so a ZIP unsafe on Windows is rejected consistently.
        name = member.filename.replace("\\", "/")
        if not name or "\0" in name or name.startswith("/"):
            raise ValueError(f"unsafe ZIP member path: {member.filename!r}")
        parts = name.split("/")
        if any(part == ".." for part in parts) or re.match(r"^[A-Za-z]:", parts[0]):
            raise ValueError(f"unsafe ZIP member path: {member.filename!r}")
        target = (destination / Path(*parts)).resolve()
        if target != destination and destination not in target.parents:
            raise ValueError(f"unsafe ZIP member path: {member.filename!r}")
    zip_file.extractall(destination)


def looks_like_message(value: Any) -> bool:
    return isinstance(value, dict) and "ts" in value and any(
        key in value for key in ("text", "files", "blocks", "attachments", "subtype", "bot_id")
    )


def collect_messages(value: Any) -> list[dict[str, Any]]:
    """Handle Slack API arrays and common slackdump wrappers."""
    found: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if looks_like_message(node) and id(node) not in seen:
                seen.add(id(node))
                found.append(node)
            for key, child in node.items():
                if key not in {"blocks", "attachments", "files"} and isinstance(child, (dict, list)):
                    walk(child)

    walk(value)
    unique: dict[str, dict[str, Any]] = {}
    for message in found:
        ts = str(message.get("ts", ""))
        if ts:
            old = unique.get(ts)
            # Slack parent messages can contain small {user, ts} reply stubs.
            # Prefer the complete copy encountered elsewhere in the dump.
            if old is None or len(message) > len(old):
                unique[ts] = message
    return list(unique.values())


def warn_missing_bounds(messages: list[dict[str, Any]], start: str, end: str | None) -> None:
    timestamps = {str(message.get("ts")) for message in messages}
    if start not in timestamps:
        print(f"warning: requested start message {start} is absent from fetched data", file=sys.stderr)
    if end and end not in timestamps:
        print(f"warning: requested end message {end} is absent from fetched data", file=sys.stderr)


def conversation_info(values: list[Any], channel_id: str | None) -> tuple[str | None, list[str]]:
    """Find conversation name and participant IDs/names in common wrappers."""
    candidates: list[str] = []
    participants: list[str] = []

    def add_participant(item: Any) -> None:
        if isinstance(item, str) and item.strip():
            participants.append(item.strip())
        elif isinstance(item, dict):
            for key in ("display_name", "real_name", "name", "user_id", "id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    participants.append(value.strip())
                    return

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            node_channel = node.get("channel_id") or node.get("channel") or node.get("id")
            for key in ("channel_name", "conversation_name"):
                if isinstance(node.get(key), str):
                    candidates.append(node[key])
            if channel_id and str(node_channel) == channel_id and isinstance(node.get("name"), str):
                candidates.append(node["name"])
            relevant = not channel_id or str(node_channel) == channel_id or any(key in node for key in ("channel_name", "conversation_name"))
            if relevant:
                for key in ("members", "participants", "member_ids"):
                    members = node.get(key)
                    if isinstance(members, list):
                        for member in members:
                            add_participant(member)
            for key, child in node.items():
                if key not in {"messages", "replies", "blocks", "attachments", "files", "users"}:
                    walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)

    for value in values:
        walk(value)
    raw = next((item.strip() for item in candidates if item.strip()), None)
    return raw, list(dict.fromkeys(participants))


def friendly_conversation_label(raw: str, users: dict[str, str] | None = None) -> str:
    """Turn Slack's generated MPDM name into a readable participant label."""
    if not raw.startswith("mpdm-"):
        return raw
    body = re.sub(r"-\d+$", "", raw[5:])
    handles = [item for item in body.split("--") if item]
    names = []
    for handle in handles:
        name = (users or {}).get(f"@{handle}", handle)
        names.append(re.sub(r"\s+", "", name))
    return "DM-" + "-".join(names)


def conversation_name(
    values: list[Any], channel_id: str | None, users: dict[str, str] | None = None
) -> str:
    raw, _ = conversation_info(values, channel_id)
    raw = raw or channel_id or "slack"
    raw = friendly_conversation_label(raw, users)
    return clean_conversation_name(raw, channel_id)


def clean_conversation_name(label: str, channel_id: str | None = None) -> str:
    """Make a conversation label safe for a default filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-.")
    return cleaned or channel_id or "slack"


def user_names(values: list[Any]) -> dict[str, str]:
    """Build Slack user ID to best available display-name mapping."""
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            user_id = node.get("id") or node.get("user_id")
            profile = node.get("profile") if isinstance(node.get("profile"), dict) else {}
            if isinstance(user_id, str) and re.fullmatch(r"[UW][A-Z0-9]+", user_id):
                chosen_name = None
                for name in (
                    profile.get("display_name"), profile.get("real_name"),
                    node.get("display_name"), node.get("real_name"), node.get("name"),
                ):
                    if isinstance(name, str) and name.strip():
                        chosen_name = name.strip()
                        found.setdefault(user_id, chosen_name)
                        break
                handle = node.get("name")
                if chosen_name and isinstance(handle, str) and handle.strip():
                    found.setdefault(f"@{handle.strip()}", chosen_name)
                bot_id = profile.get("bot_id") or node.get("bot_id")
                if chosen_name and isinstance(bot_id, str) and re.fullmatch(r"B[A-Z0-9]+", bot_id):
                    found.setdefault(bot_id, chosen_name)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    for value in values:
        walk(value)
    return found


def highlighted_user_ids(values: list[Any], username: str | None) -> set[str]:
    """Match author IDs by Slack handle, display/real name, or raw user ID."""
    if not username:
        return set()
    wanted = username.strip().lstrip("@").casefold()
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            user_id = node.get("user") or node.get("user_id") or node.get("id")
            if isinstance(user_id, str):
                profile = node.get("profile") or node.get("user_profile") or {}
                profile = profile if isinstance(profile, dict) else {}
                # IDs in user-directory records must describe users, not channels.
                if "user" in node or re.fullmatch(r"[UWB][A-Z0-9]+", user_id):
                    names = [user_id, node.get("name"), node.get("username"),
                             node.get("display_name"), node.get("real_name"),
                             profile.get("display_name"), profile.get("real_name"), profile.get("name")]
                    if any(isinstance(name, str) and name.strip().lstrip("@").casefold() == wanted for name in names):
                        found.add(user_id)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(values)
    return found


def channel_names(values: list[Any]) -> dict[str, str]:
    """Build Slack channel ID to readable channel-name mapping."""
    found: dict[str, str] = {}

    def add(channel_id: Any, name: Any) -> None:
        if not isinstance(channel_id, str) or not re.fullmatch(r"[CG][A-Z0-9]+", channel_id):
            return
        if isinstance(name, str) and name.strip():
            found.setdefault(channel_id, name.strip().lstrip("#"))

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            add(node.get("id"), node.get("name"))
            add(node.get("channel_id") or node.get("channel"), node.get("channel_name") or node.get("conversation_name"))
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    for value in values:
        walk(value)
    return found


def default_output_name(
    name: str, start: str, timezone: dt.tzinfo, output_format: str,
    end: str | None = None,
) -> Path:
    """Name output from the actual earliest and latest included post times."""
    def stamp(value: str) -> str:
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).astimezone(timezone).strftime('%Y-%m-%d-%H-%M-%S')

    extension = {"html": "html", "markdown": "md", "pdf": "pdf"}[output_format]
    return Path(f"{name}-{stamp(start)}-to-{stamp(end if end is not None else start)}.{extension}")


def require_available_output(output: Path, force: bool) -> None:
    """Refuse to replace an existing output unless explicitly allowed."""
    if str(output) != "-" and output.exists() and not force:
        raise FileExistsError(f"output already exists: {output}; use -F/--force to replace it")


def confirm_output_overwrite(
    outputs: list[Path], force: bool, approved: set[Path],
) -> None:
    """Ask once for existing output paths; keep approval scoped to those files."""
    existing = list(dict.fromkeys(
        path for path in outputs
        if str(path) != "-" and path.exists() and path not in approved
    ))
    if force or not existing:
        return
    if sys.stdin.isatty():
        files = ", ".join(str(path) for path in existing)
        notice = f"Output already exists: {files}."
        quoted_files = ", ".join(f'"{path}"' for path in existing)
        question = f"Overwrite {quoted_files}? [y/N] "
        print(
            notice + "\nIn the future, you can use -F/--force to skip this prompt and force overwrite.\n" + question,
            end="", file=sys.stderr, flush=True,
        )
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            answer = ""
        if answer in {"y", "yes"}:
            approved.update(existing)
            return
    require_available_output(existing[0], False)


def infer_output_format(output: Path | None) -> str:
    """Infer a text output format from its conventional filename suffix."""
    suffix = output.suffix.lower() if output else ""
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in (".htm", ".html"):
        return "html"
    if suffix == ".pdf":
        return "pdf"
    return "html"


def debug_render_html_path(enabled: bool, output: Path | None, converter: str) -> Path | None:
    """Resolve the optional converter-input HTML debug path."""
    if not enabled:
        return None
    if output is None or str(output) == "-":
        return Path(f"slack-print-{converter}-input.html")
    return output.with_name(f"{output.stem}-{converter}-input.html")


def display_time(ts: str, timezone: dt.tzinfo) -> str:
    instant = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).astimezone(timezone)
    return instant.strftime("%Y-%m-%d %H:%M:%S %Z")


def conversation_heading(
    label: str | None, channel_id: str | None, markdown: bool = False,
    users: dict[str, str] | None = None,
) -> str:
    if not label:
        return "Slack"
    if channel_id and channel_id.startswith("D") and label == channel_id:
        label = "Direct message"
    label = friendly_conversation_label(label, users)
    rendered = markdown_text(label) if markdown else html.escape(label)
    is_channel = not label.startswith("DM-") and (channel_id is None or channel_id.startswith(("C", "G")))
    return f"Slack: {'#' if is_channel else ''}{rendered}"


def link_conversation_heading(title: str, url: str | None, markdown: bool = False) -> str:
    """Link only the conversation portion of a rendered Slack heading."""
    prefix = "Slack: "
    if not url or not title.startswith(prefix):
        return title
    label = title[len(prefix):]
    if markdown:
        return f"{prefix}[{label}]({url})"
    return f'{prefix}<a href="{html.escape(url, quote=True)}">{label}</a>'


def document_title(heading: str, actual_start: str | None, timezone: dt.tzinfo) -> str:
    if actual_start:
        return f"{heading} {display_time(actual_start, timezone)}"
    return f"{heading} with no messages"


def w3c_datetime(value: dt.datetime) -> str:
    """Return a W3C-compatible timestamp for HTML/PDF metadata."""
    return value.isoformat(timespec="seconds")


def emoji_codepoints(value: str) -> str:
    points = [ord(char) for char in value]
    if 0x200D not in points:
        points = [point for point in points if point != 0xFE0F]
    return "-".join(f"{point:x}" for point in points)


def unicode_emoji_image(value: str, image_format: str = "svg", size: int | None = None) -> str:
    """Return a Twemoji image for engines lacking emoji fonts."""
    base = TWEMOJI_PNG_BASE if image_format == "png" else TWEMOJI_SVG_BASE
    suffix = "png" if image_format == "png" else "svg"
    url = f"{base}/{emoji_codepoints(value)}.{suffix}"
    if image_format == "background":
        escaped_url = html.escape(f"{TWEMOJI_PNG_BASE}/{emoji_codepoints(value)}.png", quote=True)
        return (
            f'<span class="emoji emoji-bg" role="img" aria-label="{html.escape(value, quote=True)}" '
            f'title="{html.escape(value, quote=True)}" style="background-image:url(&quot;{escaped_url}&quot;)"></span>'
        )
    dimensions = f' width="{size}" height="{size}"' if size else ""
    return f'<img class="emoji" src="{url}" alt="{html.escape(value)}" title="{html.escape(value)}"{dimensions}>'


def rendered_emoji(
    name: str, custom_emoji: dict[str, str] | None, markdown: bool,
    image_standard: bool = False, image_format: str = "svg", image_size: int | None = None,
) -> str:
    """Render a standard Slack alias as Unicode or a workspace alias as an image."""
    path = (custom_emoji or {}).get(name)
    if path:
        if markdown:
            return f"![:{name}:]({path})"
        escaped = html.escape(name)
        if image_format == "background":
            escaped_path = html.escape(path, quote=True)
            return (
                f'<span class="emoji emoji-bg" role="img" aria-label=":{escaped}:" '
                f'title=":{escaped}:" style="background-image:url(&quot;{escaped_path}&quot;)"></span>'
            )
        dimensions = f' width="{image_size}" height="{image_size}"' if image_size else ""
        return f'<img class="emoji" src="{html.escape(path, quote=True)}" alt=":{escaped}:" title=":{escaped}:"{dimensions}>'
    toned = re.fullmatch(r"(.+?)::skin-ton(?:e)?-([2-6])", name)
    if toned and toned.group(1) in STANDARD_EMOJI:
        value = STANDARD_EMOJI[toned.group(1)] + SKIN_TONES[toned.group(2)]
        return unicode_emoji_image(value, image_format, image_size) if image_standard and not markdown else value
    if name in STANDARD_EMOJI:
        value = STANDARD_EMOJI[name]
        return unicode_emoji_image(value, image_format, image_size) if image_standard and not markdown else value
    return f"`:{name}:`" if markdown else f"<code>:{html.escape(name)}:</code>"


def channel_mention_label(
    channel_id: str, provided_name: str | None = None, channels: dict[str, str] | None = None
) -> str:
    """Return a visible Slack channel mention label."""
    name = (provided_name or "").strip() or (channels or {}).get(channel_id, "")
    return "#" + (name.strip().lstrip("#") if name else channel_id)


def html_mention(label: str, href: str | None = None) -> str:
    """Render a highlighted Slack mention label."""
    rendered = html.escape(label)
    if href:
        return f'<a class="mention" href="{html.escape(href, quote=True)}">{rendered}</a>'
    return f'<span class="mention">{rendered}</span>'


def html_channel_mention(
    channel_id: str, provided_name: str | None = None, channels: dict[str, str] | None = None,
    header_url: str | None = None,
) -> str:
    """Render a highlighted Slack channel mention, linked when the workspace is known."""
    label = channel_mention_label(channel_id, provided_name, channels)
    return html_mention(label, related_slack_channel_url(header_url, channel_id))


def html_user_mention(user_id: str, users: dict[str, str], header_url: str | None = None) -> str:
    """Render a highlighted Slack user mention, linked when the workspace is known."""
    return html_mention("@" + users.get(user_id, user_id), related_slack_user_url(header_url, user_id))


def mrkdwn(
    text: str, users: dict[str, str] | None = None, custom_emoji: dict[str, str] | None = None,
    channels: dict[str, str] | None = None, header_url: str | None = None,
) -> str:
    """Render useful Slack mrkdwn safely. Unknown constructs remain visible."""
    safe = html.escape(html.unescape(text or ""))
    safe = re.sub(
        r"&lt;(https?://[^|&]+)\|([^&]+)&gt;",
        lambda m: f'<a href="{html.escape(m.group(1), quote=True)}">{m.group(2)}</a>',
        safe,
    )
    safe = re.sub(
        r"&lt;(https?://[^&]+)&gt;",
        lambda m: f'<a href="{html.escape(m.group(1), quote=True)}">{m.group(1)}</a>',
        safe,
    )
    users = users or {}
    safe = re.sub(
        r"&lt;@([A-Z0-9]+)&gt;",
        lambda m: html_user_mention(m.group(1), users, header_url),
        safe,
    )
    safe = re.sub(
        r"&lt;#([A-Z0-9]+)(?:\|([^&]+))?&gt;",
        lambda m: html_channel_mention(m.group(1), html.unescape(m.group(2) or ""), channels, header_url),
        safe,
    )
    custom_emoji = custom_emoji or {}
    safe = EMOJI_ALIAS.sub(lambda m: rendered_emoji(m.group(1), custom_emoji, False), safe)
    safe = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"(?<!\w)\*([^*\n]+)\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"(?<!\w)_([^_\n]+)_", r"<em>\1</em>", safe)
    safe = re.sub(r"(?<!\w)~([^~\n]+)~", r"<del>\1</del>", safe)
    return safe.replace("\n", "<br>\n")


def markdown_text(
    text: str, users: dict[str, str] | None = None, custom_emoji: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
) -> str:
    """Convert common Slack mrkdwn to portable CommonMark."""
    safe = html.escape(html.unescape(text or ""))
    safe = re.sub(r"&lt;(https?://[^|&]+)\|([^&]+)&gt;", r"[\2](\1)", safe)
    safe = re.sub(r"&lt;(https?://[^&]+)&gt;", r"<\1>", safe)
    users = users or {}
    safe = re.sub(r"&lt;@([A-Z0-9]+)&gt;", lambda m: "@" + html.escape(users.get(m.group(1), m.group(1))), safe)
    safe = re.sub(
        r"&lt;#([A-Z0-9]+)(?:\|([^&]+))?&gt;",
        lambda m: html.escape(channel_mention_label(m.group(1), html.unescape(m.group(2) or ""), channels)),
        safe,
    )
    safe = re.sub(r"(?m)^&gt;(?=\s|$)", ">", safe)
    safe = re.sub(r"(?<!\w)\*([^*\n]+)\*", r"**\1**", safe)
    safe = re.sub(r"(?<!\w)~([^~\n]+)~", r"~~\1~~", safe)
    custom_emoji = custom_emoji or {}
    safe = EMOJI_ALIAS.sub(lambda m: rendered_emoji(m.group(1), custom_emoji, True), safe)
    return safe


def rich_element(
    element: dict[str, Any], users: dict[str, str], markdown: bool,
    custom_emoji: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
    header_url: str | None = None,
) -> str:
    """Render one inline Block Kit rich-text element."""
    kind = element.get("type")
    if kind == "text":
        value = str(element.get("text") or "")
        rendered = (
            markdown_text(value, users, channels=channels)
            if markdown else mrkdwn(value, users, channels=channels, header_url=header_url)
        )
    elif kind == "link":
        url = str(element.get("url") or "")
        label = str(element.get("text") or url)
        if markdown:
            rendered = f"[{markdown_text(label, users, channels=channels)}]({url})"
        else:
            rendered = f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
    elif kind == "user":
        user_id = str(element.get("user_id") or "")
        rendered = "@" + (users.get(user_id, user_id) or "unknown")
        if not markdown:
            rendered = html_user_mention(user_id, users, header_url)
    elif kind == "channel":
        channel_id = str(element.get("channel_id") or "")
        name = str(element.get("name") or "") or None
        rendered = channel_mention_label(channel_id, name, channels) if channel_id else "#channel"
        if not markdown:
            rendered = html_channel_mention(channel_id, name, channels, header_url) if channel_id else html_mention(rendered)
    elif kind == "emoji":
        name = str(element.get("name") or "emoji")
        rendered = rendered_emoji(name, custom_emoji, markdown)
    elif kind == "broadcast":
        rendered = "@" + str(element.get("range") or "channel")
    else:
        rendered = (
            markdown_text(str(element.get("text") or ""), users, channels=channels)
            if markdown else mrkdwn(str(element.get("text") or ""), users, channels=channels, header_url=header_url)
        )
    style = element.get("style") if isinstance(element.get("style"), dict) else {}
    wrappers = (("code", "`", "code"), ("bold", "**", "strong"), ("italic", "_", "em"), ("strike", "~~", "del"))
    for flag, marker, tag in wrappers:
        if style.get(flag) and rendered:
            rendered = f"{marker}{rendered}{marker}" if markdown else f"<{tag}>{rendered}</{tag}>"
    return rendered


def rich_block(
    element: dict[str, Any], users: dict[str, str], markdown: bool,
    custom_emoji: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
    header_url: str | None = None,
) -> str:
    """Render a structural rich_text element."""
    kind = element.get("type")
    children = element.get("elements") if isinstance(element.get("elements"), list) else []
    if kind == "rich_text_section":
        return "".join(rich_element(child, users, markdown, custom_emoji, channels, header_url) for child in children if isinstance(child, dict))
    if kind == "rich_text_quote":
        value = "".join(rich_element(child, users, markdown, custom_emoji, channels, header_url) for child in children if isinstance(child, dict))
        if markdown:
            return "\n".join("> " + line for line in value.splitlines())
        return f"<blockquote>{value.replace(chr(10), '<br>')}</blockquote>"
    if kind == "rich_text_preformatted":
        value = "".join(str(child.get("text") or "") for child in children if isinstance(child, dict))
        return f"```\n{value}\n```" if markdown else f"<pre><code>{html.escape(html.unescape(value))}</code></pre>"
    if kind == "rich_text_list":
        items = [rich_block(child, users, markdown, custom_emoji, channels, header_url) for child in children if isinstance(child, dict)]
        ordered = element.get("style") == "ordered"
        if markdown:
            value = "\n".join(f"{index if ordered else '-'}{'.' if ordered else ''} {item}" for index, item in enumerate(items, 1))
            if element.get("border"):
                value = "\n".join("> " + line for line in value.splitlines())
            return value
        tag = "ol" if ordered else "ul"
        value = f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>"
        return f"<blockquote>{value}</blockquote>" if element.get("border") else value
    return "".join(rich_block(child, users, markdown, custom_emoji, channels, header_url) for child in children if isinstance(child, dict))


def render_blocks(
    message: dict[str, Any], users: dict[str, str] | None = None, markdown: bool = False,
    custom_emoji: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
    header_url: str | None = None,
) -> str:
    """Render supported Block Kit content; return empty when no useful block exists."""
    users = users or {}
    blocks = message.get("blocks") if isinstance(message.get("blocks"), list) else []
    rendered: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "rich_text":
            parts = [rich_block(item, users, markdown, custom_emoji, channels, header_url) for item in block.get("elements", []) if isinstance(item, dict)]
            value = ("\n\n" if markdown else "").join(part for part in parts if part)
        elif kind in {"section", "header"}:
            text_object = block.get("text") if isinstance(block.get("text"), dict) else {}
            raw = str(text_object.get("text") or "")
            value = (
                markdown_text(raw, users, custom_emoji, channels)
                if markdown else mrkdwn(raw, users, custom_emoji, channels, header_url)
            )
            fields = block.get("fields") if isinstance(block.get("fields"), list) else []
            field_values = []
            for field in fields:
                if isinstance(field, dict) and field.get("text"):
                    field_values.append(
                        markdown_text(str(field["text"]), users, custom_emoji, channels)
                        if markdown else mrkdwn(str(field["text"]), users, custom_emoji, channels, header_url)
                    )
            if field_values:
                value += ("\n" if markdown else "<br>") + (" | ".join(field_values))
            if kind == "header" and value:
                value = f"**{value}**" if markdown else f"<strong>{value}</strong>"
        elif kind == "divider":
            value = "---" if markdown else "<hr>"
        elif kind == "image":
            value = str(block.get("alt_text") or block.get("title", {}).get("text") or "")
            value = markdown_text(value, users, channels=channels) if markdown else html.escape(value)
        else:
            # Preserve visible labels from unsupported interactive/context blocks.
            labels: list[str] = []
            def collect(node: Any) -> None:
                if isinstance(node, dict):
                    if isinstance(node.get("text"), str):
                        labels.append(node["text"])
                    for child in node.values():
                        if isinstance(child, (dict, list)):
                            collect(child)
                elif isinstance(node, list):
                    for child in node:
                        collect(child)
            collect(block)
            raw = " ".join(dict.fromkeys(label for label in labels if label.strip()))
            value = (
                markdown_text(raw, users, channels=channels)
                if markdown else mrkdwn(raw, users, channels=channels, header_url=header_url)
            )
        if value:
            rendered.append(value)
    result = ("\n\n" if markdown else "<br>\n").join(rendered)
    # Slack sometimes serializes a quoted numbered line as rich_text_list even
    # though the message fallback retains the leading quote marker. Preserve
    # the author's visible intent in that disagreement.
    fallback = html.unescape(str(message.get("text") or ""))
    quoted_number = re.search(r"(?m)^>\s*(\d+)\.\s+", fallback)
    if quoted_number and ("> " not in result if markdown else "<blockquote>" not in result):
        number = quoted_number.group(1)
        if markdown:
            result = re.sub(rf"(?m)^{re.escape(number)}\.\s+", f"> {number}. ", result, count=1)
        else:
            result = re.sub(
                r"<ol><li>(.*?)</li></ol>",
                lambda match: f"<blockquote>{number}. {match.group(1)}</blockquote>",
                result,
                count=1,
                flags=re.DOTALL,
            )
    return result


def candidate_paths(file: dict[str, Any], source_root: Path) -> Iterable[Path]:
    for key in ("local_path", "path", "file_path", "url_private_download", "url_private"):
        raw = file.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        parsed = urlparse(raw)
        if parsed.scheme in ("", "file"):
            path = Path(unquote(parsed.path if parsed.scheme else raw))
            yield path if path.is_absolute() else source_root / path
    # Slackdump stores attachments as FILE_ID-sanitized_name. Its legacy
    # JSON can retain remote URLs even with -update-links enabled.
    file_id = file.get("id")
    if isinstance(file_id, str) and re.fullmatch(r"F[A-Za-z0-9]+", file_id):
        yield from sorted(source_root.rglob(f"{file_id}-*"))
    name = file.get("name")
    if isinstance(name, str) and name:
        yield from source_root.rglob(name)


def assets_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}-files")


def has_linkable_files(
    messages: list[dict[str, Any]], source_root: Path, start: str, end: str | None,
    single_thread: bool = False, include_custom_emoji: bool = True,
) -> bool:
    selected = select_messages(messages, start, end, single_thread)
    for message in selected:
        for item in message.get("files") or []:
            if isinstance(item, dict) and any(path.is_file() for path in candidate_paths(item, source_root)):
                return True
    if include_custom_emoji:
        with tempfile.TemporaryDirectory(prefix="slack-print-asset-check-") as name:
            emoji = custom_emoji_assets(source_root, Path(name), message_emoji_names(selected))
            if any(urlparse(path).scheme not in {"http", "https"} for path in emoji.values()):
                return True
    return False


def save_files(message: dict[str, Any], source_root: Path, assets: Path) -> list[tuple[str, bool, str]]:
    saved: list[tuple[str, bool, str]] = []
    for item in message.get("files") or []:
        if not isinstance(item, dict):
            continue
        source = next((p for p in candidate_paths(item, source_root) if p.is_file()), None)
        if source is None:
            continue
        base = source.name or str(item.get("name") or item.get("id") or "file")
        name = base
        count = 2
        while (assets / name).exists() and not (assets / name).samefile(source):
            name = f"{Path(base).stem}-{count}{Path(base).suffix}"
            count += 1
        target = assets / name
        if not target.exists():
            shutil.copy2(source, target)
        mime = str(item.get("mimetype") or mimetypes.guess_type(name)[0] or "")
        saved.append((f"{assets.name}/{name}", mime.startswith("image/"), str(item.get("title") or base)))
    return saved


def author(message: dict[str, Any], users: dict[str, str] | None = None) -> str:
    user_id = message.get("user")
    if user_id:
        raw = str(user_id)
        return (users or {}).get(raw, raw)
    bot_profile = message.get("bot_profile") if isinstance(message.get("bot_profile"), dict) else {}
    for name in (bot_profile.get("name"), message.get("username")):
        if isinstance(name, str) and name.strip():
            return f"{name.strip()} [app]"
    bot_id = str(message.get("bot_id") or "")
    name = (users or {}).get(bot_id, bot_id or "unknown")
    return f"{name} [app]"


def bot_user_ids(values: list[Any]) -> set[str]:
    """Identify bot users from directory/profile records, including Slackbot."""
    found = {"USLACKBOT"}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            profile = node.get("profile") or node.get("user_profile") or {}
            profile = profile if isinstance(profile, dict) else {}
            if node.get("is_bot") or node.get("is_app_user") or profile.get("bot_id"):
                user = node.get("id") or node.get("user_id") or node.get("user")
                if isinstance(user, str) and re.fullmatch(r"[UW][A-Z0-9]+", user):
                    found.add(user)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(values)
    return found


def resolved_conversation_label(
    label: str | None, channel_id: str | None, messages: list[dict[str, Any]],
    users: dict[str, str] | None = None, participants: list[str] | None = None,
    bot_users: set[str] | None = None,
) -> str | None:
    """Infer a friendly DM label from participants or human message authors."""
    if not channel_id or not channel_id.startswith("D") or label not in (None, channel_id, "Direct message"):
        return label
    bot_users = (bot_users or set()) | {"USLACKBOT"}
    names = []
    for participant in participants or []:
        if participant in bot_users or re.fullmatch(r"B[A-Z0-9]+", participant):
            continue
        resolved = (users or {}).get(participant, participant)
        if resolved:
            names.append(resolved)
    if not names:
        names = [
            author(message, users) for message in messages
            if message.get("user") and str(message["user"]) not in bot_users
            and not str(message["user"]).startswith("B")
            and not message.get("bot_id") and not message.get("bot_profile")
            and not message.get("app_id") and message.get("subtype") != "bot_message"
        ]
    names = list(dict.fromkeys(names))
    return "DM-" + "-".join(re.sub(r"\s+", "", name) for name in names) if names else "Direct message"


def render_reactions(
    message: dict[str, Any], users: dict[str, str] | None = None,
    custom_emoji: dict[str, str] | None = None, markdown: bool = False,
    list_reactors: bool = False,
    emoji_image_format: str = "svg",
    emoji_image_size: int | None = None,
) -> str:
    """Render Slack reactions with counts and reactor names."""
    reactions = message.get("reactions") if isinstance(message.get("reactions"), list) else []
    values: list[str] = []
    listed_name_words = sum(
        len(str((users or {}).get(str(user_id), str(user_id))).split())
        for reaction in reactions
        if isinstance(reaction, dict) and isinstance(reaction.get("users"), list)
        for user_id in reaction["users"]
    )
    for reaction in reactions:
        if not isinstance(reaction, dict) or not reaction.get("name"):
            continue
        name = str(reaction["name"])
        reactor_ids = reaction.get("users") if isinstance(reaction.get("users"), list) else []
        reactor_names = [(users or {}).get(str(user_id), str(user_id)) for user_id in reactor_ids]
        count = reaction.get("count")
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = len(reactor_ids) or 1
        icon = rendered_emoji(
            name, custom_emoji, markdown, image_standard=not markdown,
            image_format=emoji_image_format, image_size=emoji_image_size,
        )
        if list_reactors:
            names = ", ".join(reactor_names) or "unknown"
            if markdown:
                values.append(f"{icon} {count} (**{names}**)")
            else:
                values.append(
                    f'<span class="reaction"><span class="reaction-type">{icon} {count}</span>'
                    f'<span class="reactor-names">(<strong>{html.escape(names)}</strong>)</span></span>'
                )
            continue
        if markdown:
            title = f" ({', '.join(reactor_names)})" if reactor_names else ""
            values.append(f"{icon} {count}{title}")
        else:
            title = html.escape(", ".join(reactor_names), quote=True)
            values.append(f'<span class="reaction" title="{title}">{icon} {count}</span>')
    if not values:
        return ""
    if list_reactors:
        stacked = listed_name_words > 8
        if markdown:
            separator = "\n" if stacked else " · "
            return "**Reactions:** " + separator.join(values)
        css_class = "reactions extended stacked" if stacked else "reactions extended"
        return f'<div class="{css_class}">' + "".join(values) + "</div>"
    return "**Reactions:** " + " · ".join(values) if markdown else '<div class="reactions">' + "".join(values) + "</div>"


SUPPRESSED_UNFURL_FLAGS = {
    "hidden", "is_hidden",
    "removed", "is_removed",
    "deleted", "is_deleted",
    "suppressed", "is_suppressed",
    "unfurl_hidden", "is_unfurl_hidden",
    "preview_hidden", "is_preview_hidden",
    "hide_preview", "hide_unfurl",
}


def metadata_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


DELETED_MESSAGE_SUBTYPES = {
    "message_deleted",
    "tombstone",
}

DELETED_MESSAGE_FLAGS = {
    "deleted", "is_deleted",
    "hidden", "is_hidden",
    "tombstone", "is_tombstone",
}


def message_deleted(message: dict[str, Any]) -> bool:
    """Return true when Slack metadata marks the message itself as deleted."""
    subtype = str(message.get("subtype") or "").strip().lower()
    return subtype in DELETED_MESSAGE_SUBTYPES or any(metadata_truthy(message.get(flag)) for flag in DELETED_MESSAGE_FLAGS)


def message_edit_timestamp(message: dict[str, Any]) -> str | None:
    edited = message.get("edited")
    if isinstance(edited, dict):
        value = edited.get("ts") or edited.get("timestamp")
        if value:
            return str(value)
    for key in ("edited_ts", "last_edit_ts", "updated_ts"):
        value = message.get(key)
        if value:
            return str(value)
    return None


def message_meta_text(message: dict[str, Any], timezone: dt.tzinfo) -> str:
    values: list[str] = []
    edit_ts = message_edit_timestamp(message)
    if edit_ts and ts_number(edit_ts) > 0:
        values.append(f"edited {display_time(edit_ts, timezone)}")
    if message_deleted(message):
        values.append("deleted")
    return "; ".join(values)


def deleted_marker(markdown: bool = False) -> str:
    label = "This message was deleted."
    return f"*{label}*" if markdown else f'<p class="deleted-marker">{label}</p>'


def is_suppressed_unfurl(attachment: dict[str, Any]) -> bool:
    """Return true when Slack metadata says a link preview should not render."""
    return any(metadata_truthy(attachment.get(flag)) for flag in SUPPRESSED_UNFURL_FLAGS)


def render_previews(
    message: dict[str, Any], users: dict[str, str] | None = None, markdown: bool = False,
    channels: dict[str, str] | None = None,
    header_url: str | None = None,
) -> str:
    """Render Slack attachment/unfurl metadata as readable link preview cards."""
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    cards: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if is_suppressed_unfurl(attachment):
            continue
        title = str(attachment.get("title") or "").strip()
        url = str(attachment.get("title_link") or attachment.get("original_url") or attachment.get("from_url") or "").strip()
        source = str(attachment.get("service_name") or attachment.get("author_name") or "").strip()
        description = str(attachment.get("text") or attachment.get("fallback") or "").strip()
        image_url = str(attachment.get("thumb_url") or attachment.get("image_url") or "").strip()
        fields = attachment.get("fields") if isinstance(attachment.get("fields"), list) else []
        if not any((title, url, source, description, image_url, fields)):
            continue
        if markdown:
            lines: list[str] = []
            if source:
                lines.append(f"**{markdown_text(source, users, channels=channels)}**")
            if title:
                rendered_title = markdown_text(title, users, channels=channels)
                lines.append(f"[{rendered_title}]({url})" if url else rendered_title)
            elif url:
                lines.append(f"<{url}>")
            if description and description != title:
                lines.append(markdown_text(description, users, channels=channels))
            for field in fields:
                if not isinstance(field, dict):
                    continue
                field_title = markdown_text(str(field.get("title") or ""), users, channels=channels)
                field_value = markdown_text(str(field.get("value") or ""), users, channels=channels)
                if field_title or field_value:
                    lines.append(f"**{field_title}:** {field_value}" if field_title else field_value)
            if image_url:
                lines.append(f"![{markdown_text(title or source or 'link preview', channels=channels)}]({image_url})")
            cards.append("\n".join("> " + line for line in lines))
        else:
            parts: list[str] = []
            if source:
                parts.append(f'<div class="preview-source">{html.escape(source)}</div>')
            if title:
                safe_title = html.escape(title)
                parts.append(f'<a class="preview-title" href="{html.escape(url, quote=True)}">{safe_title}</a>' if url else f'<div class="preview-title">{safe_title}</div>')
            elif url:
                parts.append(f'<a class="preview-title" href="{html.escape(url, quote=True)}">{html.escape(url)}</a>')
            if description and description != title:
                parts.append(f'<div class="preview-text">{mrkdwn(description, users, channels=channels, header_url=header_url)}</div>')
            for field in fields:
                if isinstance(field, dict) and (field.get("title") or field.get("value")):
                    parts.append(
                        f'<div class="preview-field"><strong>{html.escape(str(field.get("title") or ""))}</strong> '
                        f'{mrkdwn(str(field.get("value") or ""), users, channels=channels, header_url=header_url)}</div>'
                    )
            if image_url:
                parts.append(f'<img class="preview-image" src="{html.escape(image_url, quote=True)}" alt="{html.escape(title or source or "link preview")}">')
            cards.append('<aside class="link-preview">' + "".join(parts) + "</aside>")
    return "\n\n".join(cards) if markdown else "".join(cards)


def render_message(
    message: dict[str, Any], source_root: Path, assets: Path, timezone: dt.tzinfo, include_attachments: bool,
    users: dict[str, str] | None = None, slack_url: str | None = None,
    custom_emoji: dict[str, str] | None = None,
    list_reactors: bool = False,
    emoji_image_format: str = "svg",
    emoji_image_size: int | None = None,
    channels: dict[str, str] | None = None,
    include_previews: bool = True,
    highlighted: bool = False,
    post_links: bool = True,
) -> str:
    ts = str(message.get("ts"))
    stamp = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).astimezone(timezone)
    pid = post_id(ts)
    body = render_blocks(message, users, custom_emoji=custom_emoji, channels=channels, header_url=slack_url) or mrkdwn(
        str(message.get("text") or ""), users, custom_emoji, channels, slack_url
    )
    if message_deleted(message):
        body = body + deleted_marker() if body else deleted_marker()
    previews = render_previews(message, users, channels=channels, header_url=slack_url) if include_previews else ""
    reactions = render_reactions(
        message, users, custom_emoji, list_reactors=list_reactors,
        emoji_image_format=emoji_image_format, emoji_image_size=emoji_image_size,
    )
    files = save_files(message, source_root, assets) if include_attachments else []
    timestamp_html = f'<time datetime="{stamp.isoformat()}">{stamp.strftime("%Y-%m-%d %H:%M:%S %Z")}</time>'
    if post_links:
        timestamp_href = html.escape(slack_url, quote=True) if slack_url else f"#{pid}"
        timestamp_html = f'<a class="post-time" href="{timestamp_href}">{timestamp_html}</a>'
    else:
        timestamp_html = f'<strong class="post-time">{timestamp_html}</strong>'
    file_html = []
    for href, is_image, title in files:
        escaped_href = html.escape(href, quote=True)
        escaped_title = html.escape(title)
        if is_image:
            file_html.append(f'<a href="{escaped_href}"><img loading="lazy" src="{escaped_href}" alt="{escaped_title}"></a>')
        else:
            file_html.append(f'<a class="file" href="{escaped_href}">📎 {escaped_title}</a>')
    meta = message_meta_text(message, timezone)
    meta_html = f'<span class="message-meta">{html.escape(meta)}</span>' if meta else ""
    highlight_attributes = ' class="user-highlight" style="background-color:#e8f4ff"' if highlighted else ""
    return (
        f'<article id="{pid}"{highlight_attributes}><header>{timestamp_html} '
        f'<span class="author">{html.escape(author(message, users))}</span>{meta_html}</header>'
        f'<div class="body">{body}</div>{previews}{reactions}{"".join(file_html)}</article>'
    )


def render_markdown_message(
    message: dict[str, Any], source_root: Path, assets: Path, timezone: dt.tzinfo, include_attachments: bool,
    users: dict[str, str] | None = None, slack_url: str | None = None,
    custom_emoji: dict[str, str] | None = None,
    list_reactors: bool = False,
    channels: dict[str, str] | None = None,
    include_previews: bool = True,
    post_links: bool = True,
) -> str:
    ts = str(message.get("ts"))
    stamp = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).astimezone(timezone)
    pid = post_id(ts)
    timestamp_href = slack_url or f"#{pid}"
    meta = message_meta_text(message, timezone)
    timestamp_text = stamp.strftime('%Y-%m-%d %H:%M:%S %Z')
    if post_links:
        timestamp_text = f"[{timestamp_text}]({timestamp_href})"
    heading = f"**{timestamp_text} · {author(message, users)}**"
    if meta:
        heading += f" _{markdown_text(meta)}_"
    body = render_blocks(message, users, markdown=True, custom_emoji=custom_emoji, channels=channels) or markdown_text(
        str(message.get("text") or ""), users, custom_emoji, channels
    )
    if message_deleted(message):
        body = body + "\n\n" + deleted_marker(True) if body else deleted_marker(True)
    lines = [
        f'<a id="{pid}"></a>',
        heading,
        "",
        body,
    ]
    reactions = render_reactions(message, users, custom_emoji, markdown=True, list_reactors=list_reactors)
    previews = render_previews(message, users, markdown=True, channels=channels) if include_previews else ""
    if previews:
        lines.extend(("", previews))
    if reactions:
        lines.extend(("", reactions))
    files = save_files(message, source_root, assets) if include_attachments else []
    for href, is_image, title in files:
        escaped_title = title.replace("[", "\\[").replace("]", "\\]")
        if is_image:
            lines.extend(("", f"![{escaped_title}]({href})"))
        else:
            lines.extend(("", f"[📎 {escaped_title}]({href})"))
    return "\n".join(lines)


def indent_markdown_list(value: str) -> str:
    lines = value.splitlines()
    if not lines:
        return "-"
    return "- " + lines[0] + "\n" + "\n".join("  " + line for line in lines[1:])


def select_messages(
    messages: list[dict[str, Any]], start: str, end: str | None, single_thread: bool = False,
) -> list[dict[str, Any]]:
    """Select the same range and thread replies for downloads and rendering."""
    low, high = float(start), float(end) if end else float("inf")
    in_range = [m for m in messages if low <= ts_number(m.get("ts")) <= high]
    if single_thread:
        # Without an explicit end, membership alone selects the whole thread.
        candidates = messages if end is None else in_range
        selected = [
            message for message in candidates
            if str(message.get("ts")) == start or str(message.get("thread_ts") or "") == start
        ]
    else:
        selected_parent_ts = {
            str(message.get("ts"))
            for message in in_range
            if not message.get("thread_ts") or str(message.get("thread_ts")) == str(message.get("ts"))
        }
        selected_by_ts = {str(message.get("ts")): message for message in in_range}
        for message in messages:
            thread_ts = str(message.get("thread_ts") or "")
            ts = str(message.get("ts") or "")
            if thread_ts in selected_parent_ts and ts:
                selected_by_ts[ts] = message
        selected = list(selected_by_ts.values())
    return selected


def make_document(
    messages: list[dict[str, Any]],
    start: str,
    end: str | None,
    source_root: Path,
    output: Path,
    timezone: dt.tzinfo,
    include_attachments: bool = True,
    output_format: str = "html",
    assets_dir: Path | None = None,
    conversation_label: str | None = None,
    participants: list[str] | None = None,
    single_thread: bool = False,
    users: dict[str, str] | None = None,
    channel_id: str | None = None,
    attribution: bool = True,
    header_url: str | None = None,
    list_reactors: bool = False,
    style_profile: str = "html",
    channels: dict[str, str] | None = None,
    include_previews: bool = True,
    include_custom_emoji: bool = True,
    highlight_users: set[str] | None = None,
    post_links: bool = True,
    bot_users: set[str] | None = None,
) -> int:
    selected = select_messages(messages, start, end, single_thread)
    highlight_users = highlight_users or set()
    by_ts = {str(m["ts"]): m for m in selected}
    top = [m for m in selected if not m.get("thread_ts") or str(m.get("thread_ts")) == str(m.get("ts"))]
    replies: dict[str, list[dict[str, Any]]] = {}
    for message in selected:
        parent = str(message.get("thread_ts") or "")
        if parent and parent != str(message.get("ts")):
            replies.setdefault(parent, []).append(message)
    top.sort(key=lambda m: ts_number(m.get("ts")))
    for values in replies.values():
        values.sort(key=lambda m: ts_number(m.get("ts")))
    actual_start = str(min(selected, key=lambda m: ts_number(m.get("ts")))["ts"]) if selected else None
    actual_end = str(max(selected, key=lambda m: ts_number(m.get("ts")))["ts"]) if selected else None
    participants = participants or []
    conversation_label = resolved_conversation_label(conversation_label, channel_id, selected, users, participants, bot_users)

    output.parent.mkdir(parents=True, exist_ok=True)
    assets = assets_dir or assets_path(output)
    include_custom_emoji = include_attachments and include_custom_emoji
    if include_attachments or include_custom_emoji:
        assets.mkdir(exist_ok=True)
    custom_emoji = custom_emoji_assets(source_root, assets, message_emoji_names(selected)) if include_custom_emoji else {}
    orphan_ts = [key for key in replies if key not in by_ts]
    if output_format == "markdown":
        title = conversation_heading(conversation_label, channel_id, True, users)
        title = link_conversation_heading(title, header_url if post_links else None, True)
        parts = [f"# {title}"]
        if actual_start and actual_end:
            parts.append(f"From {display_time(actual_start, timezone)} through {display_time(actual_end, timezone)}")
        else:
            parts.append("No messages")
        if participants:
            parts.append("**Participants:** " + ", ".join(markdown_text(item) for item in participants))
        parts.append("---")
        for message in top:
            ts = str(message["ts"])
            parts.append(render_markdown_message(
                message, source_root, assets, timezone, include_attachments, users,
                related_slack_message_url(header_url, channel_id, str(message["ts"])),
                custom_emoji,
                list_reactors,
                channels,
                include_previews,
                post_links,
            ))
            children = replies.get(ts, [])
            if children:
                parts.extend(("", "Replies:", ""))
                parts.extend(
                    indent_markdown_list(render_markdown_message(
                        reply, source_root, assets, timezone, include_attachments, users,
                        related_slack_message_url(header_url, channel_id, str(reply["ts"])),
                        custom_emoji,
                        list_reactors,
                        channels,
                        include_previews,
                        post_links,
                    ))
                    for reply in children
                )
            parts.append("\n---")
        if orphan_ts:
            parts.append("## Thread replies whose parent is outside this range")
            for key in orphan_ts:
                parts.extend(
                    indent_markdown_list(render_markdown_message(
                        reply, source_root, assets, timezone, include_attachments, users,
                        related_slack_message_url(header_url, channel_id, str(reply["ts"])),
                        custom_emoji,
                        list_reactors,
                        channels,
                        include_previews,
                        post_links,
                    ))
                    for reply in replies[key]
                )
        if attribution:
            parts.append(f"---\n\n{ATTRIBUTION}")
        document = "\n\n".join(parts).rstrip() + "\n"
    else:
        reaction_image_format = "background" if style_profile == "wkhtmltopdf" else "svg"
        reaction_image_size = 18 if style_profile == "wkhtmltopdf" else None
        parts = []
        for message in top:
            ts = str(message["ts"])
            block = render_message(
                message, source_root, assets, timezone, include_attachments, users,
                related_slack_message_url(header_url, channel_id, str(message["ts"])),
                custom_emoji,
                list_reactors,
                reaction_image_format,
                reaction_image_size,
                channels,
                include_previews,
                str(message.get("user") or "") in highlight_users,
                post_links,
            )
            children = replies.get(ts, [])
            if children:
                block += '<ul class="thread">' + "".join(
                    f"<li>{render_message(reply, source_root, assets, timezone, include_attachments, users, related_slack_message_url(header_url, channel_id, str(reply['ts'])), custom_emoji, list_reactors, reaction_image_format, reaction_image_size, channels, include_previews, str(reply.get('user') or '') in highlight_users, post_links)}</li>" for reply in children
                ) + "</ul>"
            parts.append(block)
        for key in orphan_ts:
            parts.append('<section class="orphan"><h2>Thread replies</h2><ul class="thread">' + "".join(
                f"<li>{render_message(reply, source_root, assets, timezone, include_attachments, users, related_slack_message_url(header_url, channel_id, str(reply['ts'])), custom_emoji, list_reactors, reaction_image_format, reaction_image_size, channels, include_previews, str(reply.get('user') or '') in highlight_users, post_links)}</li>" for reply in replies[key]
            ) + "</ul></section>")
        metadata = []
        if participants:
            metadata.append(f"<dt>Participants</dt><dd>{html.escape(', '.join(participants))}</dd>")
        if actual_start and actual_end:
            range_line = (
                f"From {html.escape(display_time(actual_start, timezone))} through "
                f"{html.escape(display_time(actual_end, timezone))}"
            )
        else:
            range_line = "No messages"
        plain_title = conversation_heading(conversation_label, channel_id, False, users)
        pdf_subject = html.unescape(plain_title)
        page_title = document_title(pdf_subject, actual_start, timezone)
        created_at = dt.datetime.now(dt.timezone.utc).astimezone(timezone)
        title = link_conversation_heading(plain_title, header_url if post_links else None)
        footer = f"<hr><footer>{html.escape(ATTRIBUTION)}</footer>" if attribution else ""
        generator_meta = (
            '<meta name="generator" content="' + html.escape(PDF_APPLICATION, quote=True) + '">\n'
            if attribution else ""
        )
        document = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>""" + html.escape(page_title) + """</title>
<meta name="title" content=\"""" + html.escape(page_title, quote=True) + """\">
<meta name="author" content=\"""" + html.escape(PDF_AUTHOR, quote=True) + """\">
<meta name="description" content=\"""" + html.escape(pdf_subject, quote=True) + """\">
<meta name="subject" content=\"""" + html.escape(pdf_subject, quote=True) + """\">
<meta name="dcterms.created" content=\"""" + html.escape(w3c_datetime(created_at), quote=True) + """\">
""" + generator_meta + """<style>
""" + html_stylesheet(style_profile) + "\n</style></head><body><h1>" + title + "</h1><p class=\"document-range\">" + range_line + "</p><dl class=\"document-metadata\">\n" + "\n".join(metadata) + "\n</dl>\n" + "\n".join(parts) + "\n" + footer + "\n</body></html>\n"
    output.write_text(document, encoding="utf-8")
    return len(selected)


def main() -> int:
    available_converters = available_pdf_converters()
    have_pdf_converter = bool(available_converters)
    formats = ("html", "markdown", "pdf") if have_pdf_converter else ("html", "markdown")
    description = "Print a Slack channel/DM range as threaded HTML, Markdown, or PDF" if have_pdf_converter else "Print a Slack channel/DM range as threaded HTML or Markdown"
    format_help = "output format; inferred from .htm[l], .md, or .pdf suffix" if have_pdf_converter else "output format; inferred from .htm[l] or .md suffix"
    parser = ErrorLastArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""References: URL, CONVERSATION:TIME, or TIME with --channel.
With --channel and no start, fetch all available messages without time bounds.
CONVERSATION: channel ID, @alice (or alice) for a DM, #foobar for a public channel.
Names match exactly, ignoring case; ambiguous names require an ID.
TIME: YYYYMMDDHHMMSS in UTC, or any leading 4–14 digits.
Missing month/day default to 01; missing time digits become zeroes.
Examples: 2017 = 2017-01-01 00:00:00 UTC; 20171103 = 2017-11-03 00:00:00 UTC.
End dates are inclusive instants, not the entire day/month. No end means now.
Slack epoch seconds.fraction and 16-digit post IDs (optional p) still work.
Quote names in shell commands: '@alice:20171103' or '#foobar:202601'.
Without -w/--workspace or a Slack URL, use Slackdump’s current workspace and
print USING DEFAULT WORKSPACE: NAME (even with --quiet). Name lookup needs directory
metadata with --input; live runs fetch it. Mentions use available channel names
without a separate directory fetch. --single-thread needs a message
URL or Slack timestamp for its start, rather than a calendar date.
-1/--single-thread captures only that post and its replies. Omit the end
reference for the whole thread without time filtering; an end caps the range.""",
    )
    selection = parser.add_argument_group("Message selection")
    selection.add_argument("start", nargs="?", help="start URL, CONVERSATION:TIME, or TIME; omit with --channel for all messages")
    selection.add_argument("end", nargs="?", help="end URL, CONVERSATION:TIME, or TIME (default: now)")
    selection.add_argument("-c", "--channel", help="channel ID, @DM-user, or #public-channel; no start means all available messages")
    selection.add_argument(
        "-1", "--single-thread", action="store_true",
        help="only the top-level start post and its replies; omit end for the whole thread without time filtering",
    )

    slack_input = parser.add_argument_group("Slack input and authentication")
    slack_input.add_argument("-i", "--input", type=Path, help="existing slackdump JSON directory, JSON file, or ZIP")
    slack_input.add_argument("-w", "--workspace", help="workspace name; otherwise a Slack URL or the logged default selects it")
    slack_input.add_argument("-l", "--login", action="store_true", help="open Slack login and replace/save authentication")
    slack_input.add_argument("-C", "--api-config", type=Path, help="slackdump API limits TOML for dump calls")
    verbosity = slack_input.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true", help="suppress normal progress output")
    verbosity.add_argument("-v", "--verbose", action="store_true", help="show slackdump commands and progress")
    verbosity.add_argument(
        "-vv", "--very-verbose", action="store_true",
        help="enable verbose output and pass verbose flags to subprocesses",
    )

    content = parser.add_argument_group("Document content")
    content.add_argument(
        "-U", "--user-highlight", metavar="USER",
        help=("highlight this Slack user's posts in light blue in "
              + ("HTML/PDF" if have_pdf_converter else "HTML")
              + "; ignored with warning in Markdown"),
    )
    content.add_argument("-N", "--no-attribution", action="store_true", help="omit the attribution footer")
    content.add_argument(
        "-I", "--raw-user-ids", action="store_true",
        help="skip full user lookup; show raw Slack U/B IDs when names are unavailable",
    )
    content.add_argument(
        "-R", "--reactors", action="store_true",
        help="add bold reactor names in parentheses after each reaction",
    )
    content.add_argument("-V", "--no-previews", action="store_true", help="do not render Slack link preview cards")
    content.add_argument("-L", "--no-post-links", action="store_true", help="omit conversation heading links and render message timestamps in bold without post links")
    content.add_argument(
        "-E", "--no-custom-emoji", action="store_true",
        help="do not fetch or render custom emoji; also implied by --no-attachments",
    )
    attachments = content.add_mutually_exclusive_group()
    attachments.add_argument("-a", "--attachments", dest="attachments", action="store_true", help="fetch and include images/files (default)")
    attachments.add_argument("-A", "--no-attachments", dest="attachments", action="store_false", help="do not fetch or include images/files")

    output_options = parser.add_argument_group("Output and formatting")
    output_options.add_argument("-o", "--output", type=Path, help="output file, or - for stdout; default uses channel and earliest/latest included post times")
    output_options.add_argument("-F", "--force", action="store_true", help="replace an existing output file")
    output_options.add_argument(
        "-f", "--format", choices=formats,
        help=format_help,
    )
    if have_pdf_converter:
        output_options.add_argument(
            "-P", "--pdf-converter", choices=("auto", *available_converters), default="auto",
            help="PDF converter; auto prefers weasyprint when available",
        )
    output_options.add_argument("-z", "--timezone", default=None, help="IANA timezone; default: machine local timezone")
    output_options.add_argument(
        "-H", "--debug-render-html", action="store_true",
        help="write converter-input debug HTML beside output and skip conversion",
    )
    output_options.add_argument(
        "-J", "--debug-dump-json", action="store_true",
        help="write OUTPUT-json-input.json with JSON values used for rendering",
    )
    parser.set_defaults(attachments=True)
    args = parser.parse_args()
    if args.user_highlight is not None and not args.user_highlight.strip().lstrip("@").strip():
        parser.error("--user-highlight requires a nonempty Slack user name")
    approved_outputs: set[Path] = set()
    if args.very_verbose:
        args.verbose = True
    if args.api_config and not args.api_config.exists():
        parser.error(f"api config does not exist: {args.api_config}")
    all_messages = args.start is None and bool(args.channel)
    if all_messages:
        if args.single_thread:
            parser.error("--single-thread requires a start message URL or Slack timestamp")
        args.start = "0000000000.000000"  # Internal selection bound, never sent as a fetch cutoff.
    if args.start is None:
        try:
            args.start = input("Start Slack URL, CONVERSATION:TIME, or TIME (required): ").strip()
            if not args.start:
                parser.error("start post is required")
            args.end = input("End Slack URL, CONVERSATION:TIME, or TIME (ENTER for current time): ").strip() or None
        except EOFError:
            parser.error("start post is required")
        except KeyboardInterrupt:
            parser.exit(130, "\nCancelled.\n")
    try:
        channel, start = parse_ref(args.start, args.channel)
        end_channel, end = parse_ref(args.end, channel) if args.end else (channel, None)
    except ValueError as exc:
        parser.error(str(exc))
    if (channel and end_channel and not named_conversation(channel)
            and not named_conversation(end_channel) and channel != end_channel):
        parser.error("start and end posts belong to different conversations")
    channel = channel or end_channel
    if args.single_thread and calendar_reference(args.start):
        parser.error("--single-thread requires a start message URL or Slack timestamp")
    if end and ts_number(end) < ts_number(start):
        parser.error("end must not be before start")
    if not args.input and not channel:
        parser.error("channel unknown; pass --channel with a bare post ID")
    start_workspace = workspace_from_url(args.start)
    end_workspace = workspace_from_url(args.end)
    if not args.input and start_workspace and end_workspace and start_workspace != end_workspace:
        parser.error("start and end posts belong to different workspaces")
    inferred_workspace = start_workspace or end_workspace
    slackdump_workspace = args.workspace or inferred_workspace
    if (
        not args.input and args.workspace and inferred_workspace
        and workspace_name(args.workspace) != inferred_workspace
    ):
        parser.error(
            f"--workspace {args.workspace} conflicts with Slack URL workspace "
            f"{inferred_workspace}"
        )
    header_url = slack_message_url(args.start, args.workspace, channel, start)
    include_custom_emoji = args.attachments and not args.no_custom_emoji

    if args.timezone:
        try:
            from zoneinfo import ZoneInfo
            timezone = ZoneInfo(args.timezone)
        except Exception as exc:
            parser.error(f"bad timezone: {exc}")
    else:
        timezone = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc

    if args.format:
        output_format = args.format
    elif args.debug_render_html:
        output_format = "pdf"
    else:
        output_format = infer_output_format(args.output)
    pdf_converter = resolve_pdf_converter(getattr(args, "pdf_converter", "auto"))
    if args.debug_render_html and output_format != "pdf":
        parser.error("-H/--debug-render-html requires PDF output")
    if output_format == "pdf" and not pdf_converter:
        requested = getattr(args, "pdf_converter", "auto")
        if requested == "auto":
            parser.error("PDF output requires weasyprint or wkhtmltopdf on PATH")
        parser.error(f"PDF output requires {requested} on PATH")

    def check_outputs() -> tuple[Path | None, Path | None]:
        debug_json = debug_dump_json_path(args.debug_dump_json, args.output)
        debug_html = debug_render_html_path(args.debug_render_html, args.output, pdf_converter)
        paths = [path for path in (debug_html or args.output, debug_json) if path is not None]
        try:
            confirm_output_overwrite(paths, args.force, approved_outputs)
        except FileExistsError as exc:
            parser.error(str(exc))
        return debug_json, debug_html

    if args.output is not None:
        check_outputs()

    with tempfile.TemporaryDirectory(prefix="slack-print-") as temp_name:
        temp = Path(temp_name)
        slackdump_api_config = args.api_config

        def resolve_references(directory: list[Any]) -> None:
            nonlocal channel, end_channel, header_url
            if named_conversation(channel):
                channel = resolve_conversation(channel, directory)
            if named_conversation(end_channel):
                end_channel = resolve_conversation(end_channel, directory)
            if channel and end_channel and channel != end_channel:
                raise ValueError("start and end posts belong to different conversations")
            header_url = slack_message_url(args.start, slackdump_workspace, channel, start)

        if args.input:
            progress("Reading input data...", args.quiet)
            source = args.input.resolve()
            if not source.exists():
                parser.error(f"input does not exist: {args.input}")
            if zipfile.is_zipfile(source):
                with zipfile.ZipFile(source) as zip_file:
                    try:
                        extract_zip_safely(zip_file, temp)
                    except ValueError as exc:
                        parser.error(str(exc))
                root = temp
            elif source.is_file():
                root = source.parent
            else:
                root = source
            values = [json.loads(source.read_text(encoding="utf-8"))] if source.is_file() and not zipfile.is_zipfile(source) else load_json_files(root)
        else:
            if not slackdump_available():
                parser.error(
                    "slackdump was not found on PATH. Install it from "
                    "https://github.com/rusq/slackdump, or use -i/--input with an existing JSON dump or ZIP"
                )
            root = temp / "dump"
            hint = workspace_hint(args.start, args.workspace) or workspace_hint(args.end or "", None)
            try:
                progress("Checking Slack authentication...", args.quiet)
                selected_workspace = ensure_auth(hint, args.login)
                if isinstance(selected_workspace, str):
                    slackdump_workspace = slackdump_workspace or selected_workspace
                    hint = hint or selected_workspace
            except (RuntimeError, subprocess.CalledProcessError) as exc:
                parser.error(str(exc))
            lookup_values: list[Any] = []
            looked_up_users = False
            if named_conversation(channel) or named_conversation(end_channel):
                progress("Resolving Slack conversation names...", args.quiet)
                lookup_root = temp / "lookup"
                if any(name and not name.startswith("#") and named_conversation(name)
                       for name in (channel, end_channel)):
                    looked_up_users = True
                    fetch_user_directory(lookup_root, slackdump_workspace, args.verbose, args.very_verbose, args.quiet)
                lookup_types = []
                if looked_up_users:
                    lookup_types.append("im")
                if any(name and name.startswith("#") for name in (channel, end_channel)):
                    lookup_types.append("public_channel")
                fetch_channel_directory(
                    lookup_root, slackdump_workspace, args.verbose, args.very_verbose,
                    args.quiet, channel_types=",".join(lookup_types),
                )
                lookup_values = load_json_files(lookup_root)
            try:
                resolve_references(lookup_values)
            except ValueError as exc:
                parser.error(str(exc))
            dump_log_root = temp / "slackdump-logs"
            dump_log_count = 0

            def expected_dump_json(output_root: Path, target: str) -> Path:
                name = target.replace(":", "-")
                return output_root / f"{name}.json"

            def run_dump(
                command: list[str], output_root: Path, target: str, wait_label: str
            ) -> subprocess.CompletedProcess[str]:
                nonlocal dump_log_count
                dump_log_count += 1
                log_path = dump_log_root / f"dump-{dump_log_count}.log"
                if args.verbose:
                    print("running: " + " ".join(slackdump_log_command(command, log_path)), file=sys.stderr)
                return run_slackdump_dump(
                    command, args.verbose, log_path, args.quiet,
                    expected_dump_json(output_root, target), wait_label,
                )

            # v4 defaults to a SQLite dump. Legacy mode emits the low-level
            # JSON which this small, dependency-free renderer consumes.
            def dump_command(
                thread_target: bool,
                output_root: Path,
                legacy: bool = True,
                target_ts: str | None = None,
                time_to: str | None = end,
            ) -> list[str]:
                target = f"{channel}:{target_ts or start}" if thread_target else str(channel)
                command = ["slackdump", "dump"]
                if legacy:
                    command.append("-legacy")
                command += [
                    *api_config_flags(slackdump_api_config),
                    f"-files={'true' if args.attachments else 'false'}",
                    "-y", "-o", str(output_root),
                ]
                if args.attachments:
                    command.append("-update-links")
                if not thread_target and not all_messages:
                    command += ["-time-from", utc_arg(start, -1)]
                if time_to:
                    command += ["-time-to", utc_arg(time_to, 1)]
                if slackdump_workspace:
                    command += ["-workspace", slackdump_workspace]
                if args.very_verbose:
                    command.append("-v")
                command.append(target)
                return command

            def fetch_boundary_thread(boundary_ts: str) -> None:
                boundary_root = root / f"boundary-{post_id(boundary_ts)}"
                command = dump_command(True, boundary_root, False, boundary_ts, None)
                target = f"{channel}:{boundary_ts}"
                try:
                    run_dump(command, boundary_root, target, "fetching boundary Slack thread")
                    return
                except subprocess.CalledProcessError:
                    print(
                        f"Boundary Slack thread fetch failed for {boundary_ts}; retrying through legacy output...",
                        file=sys.stderr,
                    )
                legacy_command = dump_command(True, boundary_root, True, boundary_ts, None)
                try:
                    run_dump(legacy_command, boundary_root, target, "fetching boundary Slack thread")
                except subprocess.CalledProcessError as exc:
                    print(
                        f"warning: could not fetch full boundary thread {boundary_ts} "
                        f"(exit status {exc.returncode}); late replies may be missing",
                        file=sys.stderr,
                    )

            command = dump_command(args.single_thread, root, True)
            target = f"{channel}:{start}" if args.single_thread else str(channel)
            fetched = False
            try:
                progress("Fetching Slack conversation...", args.quiet)
                run_dump(command, root, target, "fetching Slack conversation")
                fetched = True
            except subprocess.CalledProcessError:
                if args.single_thread:
                    print(
                        "Direct Slack thread fetch failed; retrying slower channel range fetch...",
                        file=sys.stderr,
                    )
                    shutil.rmtree(root, ignore_errors=True)
                    command = dump_command(False, root)
                    target = str(channel)
                    try:
                        run_dump(command, root, target, "fetching Slack conversation")
                        fetched = True
                    except subprocess.CalledProcessError:
                        pass
                if fetched:
                    pass
                elif not sys.stdin.isatty():
                    parser.error("Slack fetch failed; run interactively with --login if authentication expired")
                else:
                    answer = input("Slack fetch failed. Log in again and retry? [Y/n] ").strip().lower()
                    if answer not in ("", "y", "yes"):
                        parser.error("Slack fetch failed")
                    try:
                        authenticate(hint)
                        progress("Retrying Slack conversation fetch...", args.quiet)
                        run_dump(command, root, target, "fetching Slack conversation")
                        fetched = True
                    except (RuntimeError, subprocess.CalledProcessError) as exc:
                        parser.error(f"Slack fetch failed after login: {exc}")
            if fetched and end and not args.single_thread:
                progress("Fetching boundary Slack threads...", args.quiet)
                boundaries = [stamp for stamp, reference in ((start, args.start), (end, args.end))
                              if not calendar_reference(reference)]
                for boundary_ts in dict.fromkeys(boundaries):
                    fetch_boundary_thread(boundary_ts)
            if not args.raw_user_ids and not looked_up_users:
                progress("Fetching Slack user names...", args.quiet)
                fetch_user_directory(
                    root, slackdump_workspace, args.verbose, args.very_verbose, args.quiet
                )
            progress("Loading fetched Slack data...", args.quiet)
            values = load_json_files(root) + lookup_values
        if args.input:
            try:
                resolve_references(values)
            except ValueError as exc:
                parser.error(str(exc))
        progress("Preparing messages...", args.quiet)
        messages = []
        for value in values:
            messages.extend(collect_messages(value))
        if not all_messages and not calendar_reference(args.start):
            warn_missing_bounds(messages, start, None)
        if end and not calendar_reference(args.end):
            if end not in {str(message.get("ts")) for message in messages}:
                print(f"warning: requested end message {end} is absent from fetched data", file=sys.stderr)
        label, participants = conversation_info(values, channel)
        users = user_names(values)
        bot_users = bot_user_ids(values)
        highlight_users = highlighted_user_ids(values, args.user_highlight) if output_format != "markdown" else set()
        channels = channel_names(values)
        if all_messages and messages:
            first_included = str(min(messages, key=lambda message: ts_number(message.get("ts")))["ts"])
            header_url = slack_message_url(args.start, slackdump_workspace, channel, first_included)
        if args.output is None:
            resolved_label = resolved_conversation_label(label, channel, messages, users, participants, bot_users)
            output_name = clean_conversation_name(resolved_label, channel) if resolved_label else conversation_name(values, channel, users)
            selected = select_messages(messages, start, end, args.single_thread)
            first_message = str(min(selected, key=lambda message: ts_number(message.get("ts")))["ts"]) if selected else start
            last_message = str(max(selected, key=lambda message: ts_number(message.get("ts")))["ts"]) if selected else start
            args.output = default_output_name(output_name, first_message, timezone, output_format, last_message)
        debug_json, debug_html = check_outputs()
        summary_output = debug_html or args.output
        forced_overwrite = args.force and str(summary_output) != "-" and summary_output.exists()
        debug_json_force = args.force or debug_json in approved_outputs
        if not args.input and include_custom_emoji:
            progress("Fetching Slack custom emoji list (names and URLs only; image counts follow)...", args.quiet)
            fetch_custom_emoji(root, slackdump_workspace, args.verbose, args.very_verbose, args.quiet)
            progress("Fetching standard emoji aliases...", args.quiet)
            fetch_standard_emoji_data(root)
            progress("Downloading emoji used in selected messages...", args.quiet)
            download_selected_emoji(
                root, message_emoji_names(select_messages(messages, start, end, args.single_thread)), args.quiet,
                emoji_cache_directory(slackdump_workspace),
            )
        to_stdout = str(args.output) == "-"
        if to_stdout and output_format != "pdf" and args.attachments and has_linkable_files(
            messages, root, start, end, args.single_thread, include_custom_emoji
        ):
            parser.error("HTML/Markdown stdout cannot include local attachment links; use -o FILE or -A/--no-attachments")
        if output_format == "pdf":
            if debug_html:
                require_available_output(debug_html, args.force or debug_html in approved_outputs)
                progress("Rendering debug HTML...", args.quiet)
                count = make_document(
                    messages, start, end, root, debug_html.resolve(), timezone,
                    args.attachments, "html", None, label or channel, participants,
                    args.single_thread, users, channel, not args.no_attribution,
                    header_url, args.reactors, pdf_converter, channels, not args.no_previews,
                    include_custom_emoji, highlight_users, post_links=not args.no_post_links, bot_users=bot_users,
                )
                if debug_json:
                    progress("Writing debug JSON...", args.quiet)
                    write_debug_json(values, debug_json, debug_json_force)
                args.output = debug_html
            elif not to_stdout:
                args.output.parent.mkdir(parents=True, exist_ok=True)
            if not debug_html:
                render_root = temp / "pdf-render"
                render_root.mkdir()
                temp_html = render_root / "document.html"
                render_progress = (
                    f'Rendering temporary HTML (highlighting user "{args.user_highlight}") ...'
                    if args.user_highlight else "Rendering temporary HTML..."
                )
                progress(render_progress, args.quiet)
                count = make_document(
                    messages, start, end, root, temp_html, timezone, args.attachments, "html", None,
                    label or channel, participants, args.single_thread, users, channel, not args.no_attribution,
                    header_url, args.reactors, pdf_converter, channels, not args.no_previews,
                    include_custom_emoji, highlight_users, post_links=not args.no_post_links, bot_users=bot_users,
                )
                if debug_json:
                    progress("Writing debug JSON...", args.quiet)
                    write_debug_json(values, debug_json, debug_json_force)
                try:
                    command = pdf_command(
                        pdf_converter,
                        temp_html, "-" if to_stdout else str(args.output.resolve()), args.verbose,
                        args.very_verbose,
                    )
                    output_options = pdf_output_options(args.verbose, to_stdout)
                    progress(f"Converting HTML to PDF with {pdf_converter}...", args.quiet)
                    subprocess.run(command, check=True, **output_options)
                except FileNotFoundError:
                    parser.error(f"PDF output requires {pdf_converter} on PATH")
                except subprocess.CalledProcessError:
                    parser.error("PDF rendering failed; rerun with --verbose for converter details")
        else:
            if to_stdout:
                suffix = ".md" if output_format == "markdown" else ".html"
                with tempfile.NamedTemporaryFile(prefix=".slack-print-", suffix=suffix, dir=Path.cwd(), delete=False) as handle:
                    stdout_render = Path(handle.name)
                try:
                    progress("Rendering document...", args.quiet)
                    count = make_document(
                        messages, start, end, root, stdout_render, timezone, args.attachments, output_format,
                        None, label or channel, participants, args.single_thread, users, channel,
                        not args.no_attribution, header_url, args.reactors, "html", channels, not args.no_previews,
                        include_custom_emoji, highlight_users, post_links=not args.no_post_links, bot_users=bot_users,
                    )
                    if debug_json:
                        progress("Writing debug JSON...", args.quiet)
                        write_debug_json(values, debug_json, debug_json_force)
                    sys.stdout.write(stdout_render.read_text(encoding="utf-8"))
                finally:
                    stdout_render.unlink(missing_ok=True)
            else:
                progress("Rendering document...", args.quiet)
                count = make_document(
                    messages, start, end, root, args.output.resolve(), timezone, args.attachments, output_format,
                    None, label or channel, participants, args.single_thread, users, channel, not args.no_attribution,
                    header_url, args.reactors, "html", channels, not args.no_previews,
                    include_custom_emoji, highlight_users, post_links=not args.no_post_links, bot_users=bot_users,
                )
                if debug_json:
                    progress("Writing debug JSON...", args.quiet)
                    write_debug_json(values, debug_json, debug_json_force)
        action = "Overwrote (force given)" if forced_overwrite else "Wrote"
        print(f"{action} {'stdout' if to_stdout else args.output} ({count} posts)", file=sys.stderr)
        if args.user_highlight and output_format == "markdown":
            print("warning: user highlighting is not supported in Markdown; -U/--user-highlight ignored", file=sys.stderr)
        elif args.user_highlight and not any(
            str(message.get("user") or "") in highlight_users
            for message in select_messages(messages, start, end, args.single_thread)
        ):
            print(f'warning: no posts were found for user "{args.user_highlight}"', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
