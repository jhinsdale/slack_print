# slack_print - Convert Slack threads to printable documents

Generate a readable, printable document from part of a Slack channel or
direct-message conversation. Output can be HTML, Markdown, or PDF.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [How to use](#how-to-use)
- [Message references](#message-references)
- [Output](#output)
- [Emoji and caching](#emoji-and-caching)
- [Command-line reference](#command-line-reference)
- [Known limits](#known-limits)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Features

The document contains:

- Top-level messages in chronological order.
- Thread replies nested below their parent message.
- A linked timestamp for every message. It targets the original Slack message
  when possible, with a stable internal-anchor fallback. Pass
  `-L/--no-post-links` for bold timestamps without links and an unlinked
  conversation heading.
- Message date, time, resolved poster name, edited timestamps, and deleted
  message markers when Slack/slackdump metadata supplies deleted/tombstone
  message records. Deleted messages hidden from the Slack UI or absent from the
  JSON input cannot be inferred.
- Common Slack formatting: links, bold, italic, strikeout, code, mentions.
- Block Kit rich-text sections, lists, quotes, code blocks, headers, fields,
  links, mentions, emoji, dividers, and visible interactive labels.
- Common standard Slack aliases such as `:thumbsup:` rendered as Unicode
  when no image mapping overrides the built-in fallback.
  Other downloaded standard and workspace custom emoji display as inline
  images. Missing emoji and runs using `--no-attachments` or
  `--no-custom-emoji` keep unknown aliases in inline-code styling.
- Message reactions displayed with emoji, counts, and resolved reactor names.
  Pass `-R/--reactors` to follow each normal reaction oval with bold resolved
  reactor display names inside normal-weight parentheses, such as
  `(`**user1, user2**`)`. Reactions flow inline and wrap when needed.
  Extra spacing keeps each reaction-plus-user-list group visually separate.
  When the resolved reactor names contain more than eight total words across a
  post, detailed mode puts each reaction group on its own line. A fake name
  such as `Example Person` counts as two words.
  Reactor names preserve Slack's returned array order to match the Slack app;
  they are not alphabetized. Slack may return fewer user names than the reaction
  count, so the oval count remains authoritative.
  HTML uses Twemoji SVG images for standard reaction emoji because PDF
  converters cannot reliably render color emoji fonts. The `wkhtmltopdf` PDF
  profile uses fixed-size Twemoji PNG background images because its older
  WebKit engine can squash SVG or `<img>` emoji. These images load from
  `cdn.jsdelivr.net` using `jdecked/twemoji` 17.0.3; HTML viewers and PDF
  generation therefore need access to that host. The completed PDF embeds the
  images and needs no later network access. A missing remote image is skipped
  rather than aborting the whole PDF. Markdown uses Unicode.
- Resolved and linked names for `@` mentions and `#channel` mentions when the
  Slack workspace URL is known. Unknown users or channels retain their Slack ID.
  Live runs fetch the full Slack user directory for author names by default;
  pass `-I/--raw-user-ids` to skip that step and show raw Slack U/B IDs when names are unavailable.
  Channel mentions use names already present in fetched data or input metadata.
  No separate channel-directory fetch is made just for mentions; unknown channels
  keep their IDs. Friendly conversation-name lookup still fetches the directory.
- Slack app and bot authors labeled as `BotName [app]`.
- Optional `-U/--user-highlight USER` light blue background for the entire post
  by one selected Slack user, including that user's thread replies. Supported
  in HTML and PDF. Markdown warns and ignores the option.
- Downloaded images displayed inline.
- Slackdump attachment filenames with a file-ID prefix are resolved even when
  legacy JSON keeps the original remote file URLs.
- Other downloaded attachments linked from the message.
- Slack link previews rendered as cards with source, linked title, description,
  fields, and thumbnail when supplied. Remote thumbnails require network access
  when opening HTML; preview text and links remain available without them.
  Pass `-V/--no-previews` to suppress preview cards while keeping the
  message links.
- A `Slack: #CHANNEL` or DM header. Only the conversation name is linked.
- The actual earliest and latest included message times. Thread replies count
  when these bounds are calculated.

## Requirements

- Python 3.10 or newer.
- [slackdump](https://github.com/rusq/slackdump) 4.x on your `PATH`.
- Optional: `weasyprint` or `wkhtmltopdf` on `PATH` for PDF output.
  WeasyPrint is preferred. wkhtmltopdf is unsupported upstream but remains
  useful when it is the only converter available.
- Permission to read the Slack conversation.

The script does not install dependencies or helper tools. Optional PDF and
inspection tools are used only when already present.

Check both commands:

```sh
python3 --version
slackdump version
```

Slackdump is required for live fetching and browser authentication. The script
checks for it before fetching and prints a clear installation message when it
is absent. Slackdump is not required with `-i/--input` and an existing JSON
dump, JSON directory, or ZIP.

## Installation

1. Download this repository using **Code → Download ZIP** on GitHub and extract
   it, or use an existing local clone.
2. Install the tools listed under [Requirements](#requirements). For live Slack
   access, make sure the `slackdump` executable is on your `PATH`. For direct
   PDF output, also put `weasyprint` or `wkhtmltopdf` on your `PATH`.
3. Open a terminal in the directory containing `slack_print.py` and check the
   command help:

```sh
python3 slack_print.py --help
```

`slack_print.py` uses Python's standard library. No additional Python packages
are required by the script itself. The external tools have their own installation
requirements. Run the examples below from this directory.

## How to use

### First run and authentication

Run without message arguments:

```sh
python3 slack_print.py -o slack-print/index.html
```

The script asks for:

1. The first Slack message URL or ID. Required when no `--channel` is supplied.
2. The final Slack message URL or ID. Press Enter to continue through the
   newest available message.

If Slack authentication is not saved, the script offers to open slackdump's
browser login. Log in there. Slackdump stores encrypted credentials in its
normal system cache. Later runs reuse that login. This script does not read or
store the Slack token itself.

PDF output uses US Letter page size.

### Command syntax

```sh
python3 slack_print.py [START_MESSAGE] [END_MESSAGE] [OPTIONS]
```

Replace `START_MESSAGE` and `END_MESSAGE` with message links, IDs, or supported
date references. Omit the end to include messages through the present. See
[Message references](#message-references) for accepted forms and date rules.

### Capture a channel or direct message

Capture all available messages in a channel or DM, without a start time:

```sh
python3 slack_print.py -c @alice -f pdf
python3 slack_print.py -c '#foobar' -o channel.html
python3 slack_print.py -c D123 -o dm.html
```

With `-c/--channel` and no start argument, no date prompts or fetch time bounds
are used. This also works with `--input`. `--single-thread` still requires an
exact start post. Default filenames use the actual earliest/latest included
posts. Without either a start or `--channel`, the interactive prompts remain.

### Start at a specific message

Generate a document from one message through the present:

```sh
python3 slack_print.py START_MESSAGE -o slack-print/index.html
```

### Write to standard output

Write the document to standard output:

```sh
python3 slack_print.py START_MESSAGE -o -
```

For file output, attachments go beside the document in a directory based on its
name. For example, `foo.html` links to files in `foo-files/`.

HTML or Markdown cannot be written to stdout when the selected messages have
local attachments or emoji images to link. Use `-o FILE` or
`-A/--no-attachments`. If only local emoji images need links,
`-E/--no-custom-emoji` also permits stdout.

For PDF, stdout is binary and should normally be redirected:

```sh
python3 slack_print.py START_MESSAGE --format pdf -o - > slack-print.pdf
```

### Choose HTML, Markdown, or PDF

Write Markdown explicitly:

```sh
python3 slack_print.py START_MESSAGE --format markdown -o slack-print/document.md
```

Write HTML explicitly:

```sh
python3 slack_print.py START_MESSAGE --format html -o slack-print/index.html
```

Write PDF when WeasyPrint or wkhtmltopdf is installed:

```sh
python3 slack_print.py START_MESSAGE --format pdf -o slack-print/document.pdf
```

The `pdf` format value appears in `--help` only when at least one PDF converter
is found on `PATH`. No PDF format or PDF-converter option appears otherwise.
A `.pdf` output name also selects PDF. The tool renders temporary HTML as US
Letter pages, converts it with the selected converter, and removes the
temporary HTML and downloaded render assets. In `auto` mode, WeasyPrint is used
when available; otherwise the tool falls back to wkhtmltopdf if it is the only
installed converter. Use `-P/--pdf-converter` to choose another installed
converter:

```sh
python3 slack_print.py START_MESSAGE --format pdf -P weasyprint -o slack-print/document.pdf
```

PDF pages use 0.4-inch left and right margins, 0.45-inch top and bottom margins,
and 11-point body text. Long text, URLs, and inline code wrap instead of being
clipped. Long messages may continue on the next page. Images keep their aspect
ratio and shrink to at most 4 inches tall so text remains the priority.
Thread replies use small aligned bullets, a left guide bar, and compact spacing
so reply boundaries stay clear. WeasyPrint-specific CSS keeps Slack quote bars
and compact reaction pills readable in PDF while leaving normal browser HTML
styling intact.

HTML output uses the normal browser stylesheet plus generally useful print CSS.
PDF conversion may use additional converter-specific stylesheet profiles.
Those compatibility rules are not included in ordinary HTML output.

When `--format` is omitted, `.htm` and `.html` select HTML; `.md` and
`.markdown` select Markdown; and `.pdf` selects PDF when available. Unknown or
missing suffixes default to HTML. The descriptive filename used without `-o`
is explained under [Output](#output) below.

### Select a message range

Generate a document for an inclusive range:

```sh
python3 slack_print.py START_MESSAGE END_MESSAGE -o slack-print/index.html
```

Live range fetches keep the channel scan bounded by the start and end message
times, then fetch the start and end threads directly so late boundary-thread
replies are still included.

### Capture a single thread

Capture only a top-level post and its complete thread:

```sh
python3 slack_print.py 'https://example.slack.com/archives/C123/p1712345678123456' -1 -o thread.html
```

`-1/--single-thread` selects the start post and messages whose `thread_ts`
points to it, excluding other posts and threads. Use the top-level post URL,
not a reply URL. With no end argument, membership alone selects the whole
thread without time filtering, including late replies. An optional end message
instead applies an inclusive time cap. This also works with `--input` data.

Live single-thread fetches first ask slackdump for the exact thread through
legacy output, without time bounds when no end is given. A slower channel-range
scan is used only when the exact-thread fetch fails, and the tool prints a
warning before doing that scan.

### Skip images and attachments

Skip all images and attachments:

```sh
python3 slack_print.py START_MESSAGE --no-attachments -o slack-print/index.html
```

### Choose a workspace or refresh login

Force a fresh Slack login:

```sh
python3 slack_print.py START_MESSAGE --login -o slack-print/index.html
```

Use a named slackdump workspace:

```sh
python3 slack_print.py START_MESSAGE --workspace WORKSPACE -o slack-print/index.html
```

For live fetches, a Slack message URL selects the saved slackdump workspace
matching its subdomain (for example, `example.slack.com` selects `example`).
`--workspace` can select the workspace when no URL identifies it. If it
conflicts with a URL workspace, the tool stops before fetching. With no URL or
`--workspace`, the tool uses Slackdump's current/default workspace and prints
`USING DEFAULT WORKSPACE: NAME` to stderr, even with `--quiet`. This also applies
with `--login`. Change the default with `slackdump workspace select NAME`.
The chosen workspace is passed explicitly to subsequent commands. If no default
can be identified among several saved workspaces, pass `-w/--workspace` or select
a default first. Existing `--input` data needs no saved-workspace selection.

### Configure API limits

Use a Slackdump API limits config:

```sh
python3 slack_print.py START_MESSAGE END_MESSAGE -C slow.toml
```

Live dump calls write Slackdump detail to temporary log files. When Slackdump
reports Slack API rate limiting, the tool prints a short wait message instead
of dumping the full Slackdump log. `-C/--api-config` is for advanced users who
already have a Slackdump API limits TOML and want this tool to pass it to dump
calls.

### Use an existing Slackdump export

Use JSON or a ZIP already produced by slackdump:

```sh
python3 slack_print.py 1712345678.123456 --channel C123 \
  --input slackdump.zip -o slack-print/index.html
```

### Choose a timezone

Choose the displayed timezone:

```sh
python3 slack_print.py START_MESSAGE --timezone America/New_York
```

Without `--timezone`, the machine's local timezone is used.

### Highlight a user

Highlight posts by one Slack user:

```sh
python3 slack_print.py START_MESSAGE -U hin -o document.html
```

Matching is exact and case-insensitive against Slack usernames, display names,
real names, or user IDs. An optional leading `@` is accepted. Quote names with
spaces, such as `-U "John Hinsdale"`. Name matching needs available user profiles;
with `-I` or input lacking profiles, use the raw Slack user ID. Posts by other
users, including replies under a highlighted parent, keep their normal
background. If no included posts match, the tool warns after the final
`Wrote FILE` message, including with `--quiet`. Markdown always warns that the
option was ignored, without a separate no-matching-posts warning.

PDF runs with `-U hin` show the selected user during rendering:

```text
Rendering temporary HTML (highlighting user "hin") ...
```

`--quiet` suppresses this progress message.

Short example:

```sh
python3 slack_print.py START -f markdown -A -o slack-print.md
```

## Message references

The easiest reference is the Slack message link from **Copy link**:

```text
https://example.slack.com/archives/C123/p1712345678123456
```

The slackdump channel-and-timestamp form also works:

```text
C123:1712345678.123456
```

A bare Slack timestamp works when `--channel` is also supplied:

```sh
python3 slack_print.py 1712345678.123456 --channel C123
```

Use a friendly conversation name instead of its ID:

```sh
python3 slack_print.py '@alice:20171103' -w example
python3 slack_print.py 'alice:20171103' -w example
python3 slack_print.py '#foobar:202601' 202602 -w example
python3 slack_print.py 20171103 --channel @alice -w example
```

`@alice` (or bare `alice`) finds your existing one-to-one DM with that user.
Usernames, display names, real names, and user IDs match exactly, ignoring
case. Multiple matching users cause an error; use `@USER_ID` or the DM channel
ID to disambiguate. `#foobar` finds a public channel by exact name, ignoring
case. Quote references containing `#` so the shell does not treat them as
comments. Live name lookup fetches Slack directories, even with `-I` when a DM
name needs user lookup. With `--input`, the supplied JSON must include the
necessary user and channel directory metadata. Lookup does not create a DM. DM-name lookup requests only one-to-one DMs
(`im`); `#channel` lookup requests only public channels (`public_channel`). These
lookups disable Slackdump's channel cache. Slack may still rate-limit listing
requests. Directories fetched for name lookup are reused
for author and channel-mention rendering during the same run.

Calendar times use **UTC** and accept `YYYYMMDDHHMMSS`, or any leading portion
from 4 through 14 digits. Missing month/day default to `01`; missing time
digits become zeroes. Invalid dates are rejected.

| Input | UTC time |
|---|---|
| `2017` | January 1, 2017, 00:00:00 |
| `201711` | November 1, 2017, 00:00:00 |
| `20171103` | November 3, 2017, 00:00:00 |
| `2017110312` | November 3, 2017, 12:00:00 |
| `20171103123` | November 3, 2017, 12:30:00 |
| `20171103123456` | November 3, 2017, 12:34:56 |

An end prefix is an **inclusive instant**, not the entire specified day or
month. Omit the end to continue through the newest available message. Calendar
input always uses UTC; `--timezone` controls only displayed times. Slack epoch
`seconds.fraction`, 16-digit post IDs (optionally prefixed with `p`), and message
URLs still work. A bare 10-digit value means a calendar prefix; use a decimal
point for epoch seconds. For `--single-thread`, the start must identify an exact
message through its URL or Slack timestamp.

Start and end messages must belong to the same channel or DM.

## Output

### File names and attachments

Without `-o`, the filename uses the conversation name and the earliest and
latest **included post** times in the selected timezone. Thread replies count
for both bounds. The requested start/end dates do not substitute for actual
post times. A single included post repeats its timestamp for both bounds.

```text
general-2024-04-05-19-34-38-to-2024-04-06-09-12-05.html
general-2024-04-05-19-34-38-to-2024-04-06-09-12-05.md
general-2024-04-05-19-34-38-to-2024-04-06-09-12-05.pdf
```

If a channel dump has no conversation name, its channel ID is used. For a DM,
the tool first uses Slack member metadata and resolved display names. If member
metadata is absent, it falls back to human authors visible in the selected
messages. App/bot authors are excluded from this inferred heading and filename;
their posts remain in the document. This includes Slackbot and user accounts
marked as bots/apps in available user profiles.
The same friendly label is used in the heading and default filename, such as
`DM-user-alpha-UserBeta-2026-07-12-22-22-00-to-2026-07-13-09-00-00.html`. With attachments enabled for HTML
or Markdown, a directory named from the output file is created beside it:

```text
slack-print/
├── index.html
└── index-files/
    ├── diagram.png
    └── report.pdf
```

Move the HTML or Markdown file and its `-files` directory together.

### Overwrite existing files

An existing output file is never replaced by default. When `-o` supplies the
filename, it is checked before authentication, fetching, or reading input.
Without `-o`, the exact filename is known only after messages are loaded and
both included time bounds and the conversation name are resolved. Clash checks
then run before emoji downloads and rendering. There is no early filename guess;
a default-name clash can require fetching messages first. Explicit `-o` paths
are still checked before fetching. Debug filenames use the same range-based
stem and are checked together with the output. No extra name lookup is performed.

In an interactive terminal, existing output files trigger one overwrite prompt
that names the files and reminds you about `-F/--force`. Press Enter or answer
anything other than `y` or `yes` to stop without replacing them. Answer `y` or
`yes` to allow replacement for this run. Ctrl-C declines without a traceback.
Existing debug HTML and JSON files are
included in the check. Without an interactive terminal, existing files cause
an error. Pass `-F/--force` to replace them without prompting.
When force replaces the reported output file, the final summary says
`Overwrote (force given) FILE (N posts)`. New files still say `Wrote FILE`,
even with force enabled.

The prompt uses three lines:

```text
Output already exists: foobar.pdf.
In the future, you can use -F/--force to skip this prompt and force overwrite.
Overwrite "foobar.pdf"? [y/N]
```

```sh
python3 slack_print.py START_MESSAGE -o slack-print/index.html --force
```

When replacement is refused, the error appears first, followed by a blank line
and the command usage hint.

### Document headers and metadata

Every output begins with `Slack: #CHANNEL` for a named channel, or `Slack:
CONVERSATION` for a direct message. This is followed by `From START through
END`. These times are the actual earliest and latest included messages, after
filtering, including thread replies. Additional metadata includes:

HTML `<title>` and PDF Title use the same compact title, formatted as
`Slack: #CHANNEL START`. PDF Author is `Slack Print`, Subject is the channel or
DM heading, Created is the render time, and Application/Creator is
`Slack Print by John K. Hinsdale` when the converter supports those fields.
`-N/--no-attribution` suppresses only the visible footer and this
Application/Creator metadata; Title, Author, Subject, and Created remain.

In the header, `Slack:` is plain text. The channel or DM name alone links to
the Slack start message when its URL can be constructed. Each message's
timestamp also links to its original Slack message. Without a known Slack
domain, these links remain plain or fall back to stable internal anchors.
Pass `-L/--no-post-links` to render message timestamps in bold without links
in HTML, Markdown, and PDF. This also removes the conversation heading link.

Slack-generated multi-person DM names such as
`mpdm-user-alpha--user-beta--caseyexample--user-gamma-1` become friendly names
such as `DM-user-alpha-user-beta-CaseyExample-user-gamma`. Slack's collision
suffix is omitted.
Raw `D...` direct-message IDs are not shown as document names when participant
or author names can be inferred. The raw ID remains only where required inside
the original Slack message URL.

- Conversation name, when supplied by slackdump. Otherwise a channel ID or
  inferred friendly DM participant label is shown.
- Participant names or IDs, when supplied by slackdump.

### PDF rendering

PDF embeds displayed images during conversion. Images remain intact rather
than splitting across pages, so some pages may end with unused space. Temporary
PDF render HTML and render assets are removed afterward.
The preferred PDF backend is WeasyPrint. wkhtmltopdf remains available as an
unsupported legacy fallback when it is the only practical converter on a
machine. The HTML document remains the primary artifact and is kept friendly to
browser viewing, browser print-to-PDF, and future converter backends.

### Temporary files and cleanup

Temporary slackdump output and extracted ZIP contents are removed on success
or failure. This includes separately fetched workspace user lists and channel
lists fetched to resolve friendly conversation names. Saved slackdump authentication is intentionally retained. User-provided
JSON and ZIP input files are never removed.

## Emoji and caching

Live runs with attachments enabled use `slackdump emoji -files=false` to fetch
the workspace emoji list unless `-E/--no-custom-emoji` is passed.
`-A/--no-attachments` also implies `-E/--no-custom-emoji`. Only images referenced by
selected messages and replies (including reactions and Block Kit emoji) are
downloaded, after resolving aliases. These images are linked from the output
asset directory. Existing `--input` data can render custom emoji when it
contains a `custom-emoji/` directory with downloaded emoji files. Custom emoji
images are cached in `/tmp/slack-emoji/<workspace>`. Each live run fetches the
current emoji list, then reuses cached images and downloads only needed images
with new URLs or missing cache files. Aliases use their target image. Removed
emoji are no longer selected; older cached files may remain until `/tmp` is
cleared. Deleting the cache is safe. If the workspace cannot be identified or
the cache is unavailable, downloads still work without caching. Unused emoji
images are not downloaded. Download progress shows successful downloads out of
the total needed, plus elapsed seconds, with updates after each image and
every 15 seconds during a wait. Failures are counted separately. `--quiet`
suppresses these progress messages. Cache reuse is reported separately.
Temporary render copies are removed when the run ends; cached images remain
for later runs.
If an image download fails, its remote URL remains available to the renderer;
viewing that image then requires network access.
The initial emoji-list fetch shows elapsed waiting time only: image totals are
not known until that list arrives. Download counts appear in the later image
download stage.
The tool also reads slackdump's emoji JSON map. It automatically resolves
standard and workspace image URLs plus Slack `alias:name` chains, reducing
visible `:name:` misses. Its built-in common-alias map remains a fallback.
Live runs also fetch the complete `iamcal/emoji-data` short-name dataset once
into run-local temporary storage. This supplies the broad standard alias map
that Slackdump does not return. It is removed at the end of the run. If that
fetch fails, rendering continues with Slackdump data and built-in fallbacks.

## Command-line reference

```sh
python3 slack_print.py --help
```

Every optional setting has a short and full name:

### Message selection

| Short | Full | Purpose |
|---|---|---|
| `-c` | `--channel` | Channel ID, @DM-user, or #public-channel; omit start to capture all available messages. |
| `-1` | `--single-thread` | Only the start post and replies; omit end for the complete thread without time filtering. |

### Slack input and authentication

| Short | Full | Purpose |
|---|---|---|
| `-i` | `--input` | Read an existing JSON directory, JSON file, or ZIP. |
| `-w` | `--workspace` | Choose a saved slackdump workspace; must match a Slack URL when one is given. |
| `-l` | `--login` | Force a fresh Slack login. |
| `-C` | `--api-config` | Pass a Slackdump API limits TOML to dump calls. |
| `-q` | `--quiet` | Suppress normal progress output except the final `Wrote FILE` summary. |
| `-v` | `--verbose` | Show exact slackdump commands and detailed progress. |
| `-vv` | `--very-verbose` | Act like `--verbose` and pass native verbose flags to subprocesses. |

### Document content

| Short | Full | Purpose |
|---|---|---|
| `-U` | `--user-highlight USER` | Highlight one user's entire posts in light blue in HTML/PDF; warn and ignore in Markdown. |
| `-N` | `--no-attribution` | Omit the attribution footer and Application/Creator PDF metadata. |
| `-I` | `--raw-user-ids` | Skip full user lookup; show raw Slack U/B IDs when names are unavailable. |
| `-R` | `--reactors` | Add bold reactor names beside each reaction image and count. |
| `-V` | `--no-previews` | Suppress Slack link preview cards. |
| `-L` | `--no-post-links` | Omit the conversation heading link and render timestamps in bold without post links. |
| `-E` | `--no-custom-emoji` | Skip custom emoji fetch and rendering. Also implied by `-A/--no-attachments`. |
| `-a` | `--attachments` | Fetch and include attachments. This is the default. |
| `-A` | `--no-attachments` | Skip attachments. |

### Output and formatting

| Short | Full | Purpose |
|---|---|---|
| `-o` | `--output` | Choose the output file, or `-` for stdout. |
| `-F` | `--force` | Replace an existing output file. |
| `-f` | `--format` | Choose `html`, `markdown`, or available `pdf`. |
| `-P` | `--pdf-converter` | Choose `auto`, `weasyprint`, or `wkhtmltopdf`, limited to installed converters. |
| `-z` | `--timezone` | Choose the displayed timezone. |
| `-H` | `--debug-render-html` | Write `OUTPUT-CONVERTER-input.html` and skip conversion. |
| `-J` | `--debug-dump-json` | Write `OUTPUT-json-input.json` with JSON values used for rendering. |

General `-h/--help` remains in argparse's standard options section.

## Known limits

- Unsupported Block Kit controls preserve visible text labels. Exact interactive
  layout and behavior are not reproduced in a static document.
- Common Slack `mrkdwn` is rendered, but unusual formatting may remain literal.
- Slack HTML entities are decoded once before safe rendering, preventing quoted
  lines such as `&gt; text` from being displayed as entity source text.
- Markdown viewers differ. The Markdown output uses small HTML `<a>` elements
  for exact message anchors. Basic viewers may show or ignore those anchors.
- Deeply nested content and Slack-specific layouts are more reliable in HTML.
- Slack can return unfurl metadata for link previews that are not currently
  visible in the app. Use `-V/--no-previews` when strict suppression is
  preferred.
- PDF embeds displayed images. Arbitrary non-image Slack attachments are not
  embedded as separate files inside the PDF. Use HTML or Markdown when working
  attachment links are required.
- PDF output prefers WeasyPrint when installed. wkhtmltopdf is unsupported
  upstream, but still supported here as a legacy fallback when it is the only
  available converter. Its compatibility CSS is isolated from normal HTML.
- If a range begins inside a thread, replies whose parent is outside the range
  appear in a separate **Thread replies** section.
- Deleted or inaccessible attachments cannot be included.
- Existing `-i/--input` dumps resolve names only when their JSON includes user
  profiles or channel metadata, such as `users-TEAM.json` or
  `channels-TEAM.json` files.
- Live `-1/--single-thread` runs use exact-thread slackdump targets first.
  A slower channel-range scan is used only when the exact-thread fetch fails.

## Troubleshooting

### Authentication

If login expired, use `--login`.

If a system browser cannot be opened, run slackdump's login command directly,
then generate the document again:

```sh
slackdump workspace new YOUR_WORKSPACE
```

List saved slackdump workspaces:

```sh
slackdump workspace list
```

### Progress and diagnostics

Normal mode prints coarse progress such as `Fetching Slack conversation...`.
Use `-q/--quiet` to suppress normal progress while still printing the final
`Wrote FILE` summary, or `-v/--verbose` to show exact commands, underlying
slackdump progress, cache messages, and saved-data messages. Use
`-vv/--very-verbose` for all verbose behavior plus native verbose flags for
slackdump and the selected PDF converter. For wkhtmltopdf, this uses its
equivalent `--log-level info` setting. If slackdump fails, its captured
diagnostics are shown even without `--verbose`. Low-level PDF converter warnings
are hidden unless verbose mode is enabled. If PDF conversion
fails, the normal error identifies PDF rendering and suggests `--verbose` for
converter details users can use for diagnosis. PDF conversion progress names
the converter being used. Long Slackdump steps print a `... still ... after Ns ...`
message about every 15 seconds. If user-name lookup is still running after
about 60 seconds, the tool notes that `-I/--raw-user-ids` can skip that step.

### Save debugging files

Write the exact HTML that would be fed to the PDF converter, without running
the converter:

```sh
python3 slack_print.py START_MESSAGE --format pdf -o slack-print/document.pdf -H
```

This writes `slack-print/document-CONVERTER-input.html`, such as
`document-weasyprint-input.html` or `document-wkhtmltopdf-input.html`. The file
uses the same HTML renderer as normal HTML output, plus the selected converter
profile, so it is useful for debugging or manually feeding another converter.

To preserve the JSON values used for rendering before temporary data is removed:

```sh
python3 slack_print.py START_MESSAGE -o slack-print/index.html -J
```

This writes `slack-print/index-json-input.json`. With `-o -`, it writes
`slack-print-json-input.json`. `-J` can be used together with `-H`; both debug
files are named from the original requested output. Use the JSON file to
inspect exact Slack/slackdump fields behind rendering issues such as hidden
link previews.

## Development

Run project tests:

```sh
python3 -m unittest -v
```
