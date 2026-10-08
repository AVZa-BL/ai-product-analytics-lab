# Reading your tracking from a Google Sheet

Your tracking calls and their specifications live in a Google Sheet. `import-plan` reads that sheet and writes a tracking plan (YAML) that `propose` and `review-plan` use.

```
Google Sheet ──► import-plan ──► plan.yaml ──► propose --plan plan.yaml --doc your-gdd.md
   (reads)        (checks, cleans)  (you read it)
```

Two steps on purpose: you can open `plan.yaml`, see exactly what the sheet became, and keep it under version control. Nothing is sent to Anthropic until you run `propose`.

## What is verified, and what is not

- **Verified by tests:** the column recognition and mapping, the cleaning of types, statuses and yes/no words, both sheet layouts below, every error message, the request and response shapes of the two ways of reading Google, the redirect and token rules (against a server on this machine), and the whole chain sheet, plan, proposal.
- **Not verified:** a read from a real Google Sheet. No Google account was available where this was built. The addresses and response shapes follow Google's published behaviour, and the tests check them against stand-ins for Google, not against Google. Treat your first real read as the real test, and start with `--dry-run`.
- **Not verified:** the steps for getting an access token (below). They are the usual route, written from knowledge, untested here. Google changes its consent screens; your Workspace administrator may also block third-party OAuth access.

## Try it in three steps

1. **Look at how your sheet is read, and write nothing:**
   ```bash
   python -m tracewright import-plan "https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0" \
     --id my_game --title "My game" --identity-key player_id --dry-run
   ```
   The tool lists which column it read as what, and which it set aside, and stops. A typical result:
   ```
   tracewright: Google Sheet, tab gid=0 (header on row 1):
     event <- column A 'Tracking Call'
     property <- column B 'Parameter'
     type <- column C 'Data Type'
     required <- column D 'Mandatory?'
     ...
     ignored: J 'Jira', K 'Notes'
   dry run: would import 2 events, 6 properties; nothing written
   ```
2. **Fix whatever it got wrong** with the options below, until the list is right.
3. **Write the plan, then review it:**
   ```bash
   python -m tracewright import-plan "<same address>" --id my_game --title "My game" \
     --identity-key player_id --ignore-other-columns --out my-plan.yaml
   python -m tracewright review-plan my-plan.yaml
   ```

`--identity-key` is the property that ties an event to a player or device (repeat it for several). `--owner` sets a default owner for every event.

## Three ways to give the tool access

| Your sheet | Do this | Needs |
| --- | --- | --- |
| Anyone with the link can view | Pass the sheet's address. | Nothing else |
| Private | Pass the address and set `GOOGLE_SHEETS_ACCESS_TOKEN` (below). | A short-lived access token |
| Anything | Download the tab as CSV (File, Download, Comma Separated Values) and pass the file. | Nothing; one tab at a time |

**Sharing by link.** In the sheet: Share, General access, Anyone with the link, Viewer. Anyone who gets that address can read the sheet, so only do this for tracking specifications you are happy to share that widely, and switch it back afterwards if you prefer. A link-shared sheet is read one tab at a time: put the tab in the address with `#gid=<number>` (it is in your browser's address bar when the tab is open). Several tabs mean several sources:

```bash
python -m tracewright import-plan "<address>#gid=0" "<address>#gid=1234" --id my_game ...
```

**A private sheet, with a token.** The tool reads it through the Google Sheets API using an OAuth access token you supply. Getting one, by the usual route:

1. Open <https://developers.google.com/oauthplayground>.
2. Choose "Google Sheets API v4" and the scope `https://www.googleapis.com/auth/spreadsheets.readonly`, then "Authorize APIs" and sign in with the account that can see the sheet.
3. "Exchange authorization code for tokens" and copy the access token. It lasts about an hour.
4. Give it to the tool **through the environment, not the command line**, so it does not end up in your shell history:
   ```bash
   read -rs GOOGLE_SHEETS_ACCESS_TOKEN && export GOOGLE_SHEETS_ACCESS_TOKEN
   ```
   Paste the token and press Enter. The tool never prints it, never writes it to a file, and sends it only to `sheets.googleapis.com`. With a token, `--tab NAME` and `--all-tabs` work, because the API can list the tabs.

## Layouts that work

**One row per property, the event name repeated** (`examples/google-sheets/flat-rows.csv`). A row with no property describes the event itself:

| Tracking Call | Parameter | Data Type | Mandatory? | Allowed Values | Description | Fires when | Team | Implementation Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| level_completed | | | | | A player finishes a level | The result screen is shown | progression | Live |
| level_completed | level_id | string | Yes | | Level identifier | | | |
| level_completed | difficulty | enum | No | easy \| normal \| hard | Difficulty chosen | | | |

**The event name written once for a group of rows** (merged cells, or a name only on the first row). Add `--fill-down`; without it the tool stops at the first empty event cell and tells you so (`examples/google-sheets/merged-cells.csv`). A sheet exported with merged cells keeps the value only in the first cell of the merge, so merged cells need `--fill-down` too.

**Titles above the header.** If the headers are on row 4, say `--header-row 4`. Row numbers in every error message are the rows the sheet shows.

## Layouts that do not work

- **One row per event with the properties listed in one cell** ("player_id (string), level_id (string)"). Splitting free text into properties would be a guess, so it is not attempted. Restructure that part of the sheet, or send me an example so a proper reader can be built.
- **One column per property** (wide layout).
- **Lists and objects as property types.** A plan has no such types, so they are refused with a reason; record them as a string with `--type-map 'list=string'` if that is acceptable.
- **Headers in another language.** Name each column with `--map event="Событие"` and so on.

## What the tool recognises, and what it will not guess

[`column-names.md`](column-names.md) lists every header spelling and every type, status and yes/no word that is recognised, generated from the code. Everything else is refused, never guessed:

| You see | It means | What to do |
| --- | --- | --- |
| `these columns fit no meaning: J 'Jira', K 'Notes'` | Columns the tool cannot place | `--ignore-other-columns` to set them aside, or `--map NAME=HEADER` to use one |
| `2 columns could be 'type': B 'Type', C 'Data Type'` | Two columns both fit | `--map type='Data Type'` |
| `no column looks like the event name` | The event column has an unusual header, or the headers are lower down | `--map event=HEADER` or `--header-row N` |
| `row 7: unknown type 'currency'` | A type word that is not in the list | `--type-map 'currency=string'` |
| `row 9: unknown status 'Blocked'` | A status word that is not in the list | `--status-map 'Blocked=planned'` |
| `the event column is empty` | The name is written once for several rows | `--fill-down` |
| `not shared by link` | The sheet needs a sign-in | Share it by link, set the token, or download the CSV |

Names are kept exactly as written. If your sheet says `Level Completed`, the plan says `Level Completed`, and the review rules (`NAM-001`, `NAM-002`) will tell you it is not `object_action` snake_case. The tool does not rename your events.

The sheet usually has no metrics, so the plan has none. That is fine for `propose`; proposed metrics are added next to your events.

## Limits and safety

- Only `https://docs.google.com/spreadsheets/...` addresses are accepted. The request addresses are built by the tool from the sheet's id, and a redirect is followed only inside Google's domains, and never when a token is attached.
- A sheet over 5 MB, or more than 50 tabs, is refused.
- Hidden rows and columns are probably included; check with `--dry-run`.
- Cells are read as the text the sheet displays (formulas show their result).
- The tool reads; it never writes to your sheet.
