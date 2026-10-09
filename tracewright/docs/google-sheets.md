# Reading your tracking from a Google Sheet

Your tracking calls and their specifications live in a Google Sheet. `import-plan` reads that sheet and writes a tracking plan (YAML) that `propose` and `review-plan` use.

```
Google Sheet ──► import-plan ──► plan.yaml ──► propose --plan plan.yaml --doc your-gdd.md
   (reads)        (checks, cleans)  (you read it)
```

Two steps on purpose: you can open `plan.yaml`, see exactly what the sheet became, and keep it under version control. Nothing is sent to Anthropic until you run `propose`.

## What is verified, and what is not

- **Verified by tests:** the column recognition and mapping, the cleaning of types, statuses and yes/no words, the refusals below, two hand-written example layouts (invented to show the layouts, not copied from any real sheet), the request and response shapes of the two ways of reading Google as the author knew them, the refusal of redirects out of Google and the rule that a token never follows a redirect (against a server on this machine), and the whole chain sheet, plan, proposal.
- **Confirmed against the real Google, once:** a request to the Sheets API with a made-up token and a made-up sheet id was answered with HTTP 401 and an error message, and the tool turned that into the right advice and did not print the token. That is all it confirms: Google checks the token before it looks at the sheet, so the addresses and fields used to list and read tabs are not confirmed.
- **Not verified:** a read from a real Google Sheet, by either route. No Google account was available where this was built, and the network there blocked `docs.google.com`, so the link-shared route has not even had a real answer. Treat your first real read as the real test, and start with `--dry-run`.
- **Not verified:** the steps for getting an access token (below). They are the usual route, written from knowledge, untested here. Google changes its consent screens; your Workspace administrator may also block third-party OAuth access.

## Try it in three steps

1. **Look at how your sheet is read, and write nothing:**
   ```bash
   python -m tracewright import-plan "https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0" \
     --id my_game --title "My game" --identity-key player_id --ignore-other-columns --dry-run
   ```
   The tool reads every row, writes nothing, and shows which column it read as what, which it set aside, and then each event with the type it read for each property. Without `--ignore-other-columns`, a sheet with columns the tool cannot place stops with an error that names them instead. A typical result:
   ```
   tracewright: Google Sheet, tab gid=0 (header on row 1):
     event <- column A 'Tracking Call'
     property <- column B 'Parameter'
     type <- column C 'Data Type'
     ...
     ignored: J 'Jira', K 'Notes'
   how the cells were read (name:type, * required, ! personal data):
     level_completed (active): player_id:string*, level_id:string*, stars:integer, difficulty:enum[easy|normal|hard]
     shop_opened (planned): player_id:string*, entry_point:enum[menu|level_end|push]
   dry run: would import 2 events, 6 properties; nothing written
   ```
   Read the second block as carefully as the first: it is where a wrong type, a missing value list, or a banner row that became an event shows up.
2. **Fix whatever it got wrong** with the options below, until the list is right.
3. **Write the plan, then review it:**
   ```bash
   python -m tracewright import-plan "<same address>" --id my_game --title "My game" \
     --identity-key player_id --ignore-other-columns --out my-plan.yaml
   python -m tracewright review-plan my-plan.yaml
   ```

`--identity-key` is the property that ties an event to a player or device (repeat it for several). `--owner` sets a default owner for every event.

Choosing columns: `--map NAME=HEADER` reads a column as a meaning (`NAME` is `event`, `property`, `type`, `required`, `pii`, `allowed_values`, `description`, `event_description`, `trigger`, `owner` or `status`); `--map NAME=@E` picks by column letter, which is the only way when two headers are identical or empty; `--ignore-column HEADER` (or `@E`) sets a column aside even though its header is recognised, for example a per-property Status that is not the event's status.

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

`--fill-down` fills **the event name only**. A Status, Team or Trigger cell merged over the rows of *several different events* reaches only the first of them; the others have no value, a missing status is read as `active` (the plan default), and the tool says so in a note. Write those cells on a row of every event, or fix the plan afterwards.

A column headed just `Description` is read as the **property's** description (on a row with no property, as the event's). If it describes the event, name it: `--map event_description=Description`. The dry run says which reading it used.

**Titles above the header.** If the headers are on row 4, say `--header-row 4`. Row numbers in every error message are the rows the sheet shows.

## Layouts that do not work

- **One row per event with the properties listed in one cell** ("player_id (string), level_id (string)"). Splitting free text into properties would be a guess, so it is not attempted. Restructure that part of the sheet, or send me an example so a proper reader can be built.
- **One column per property** (wide layout).
- **Lists and objects as property types.** A plan has no such types, so they are refused with a reason; record them as a string with `--type-map 'list=string'` if that is acceptable.
- **Headers in another language.** Name each column with `--map event="Событие"` and so on.
- **Section banners, legends and notes in the event column** (`=== MONETISATION ===`). Every non-empty event cell becomes an event. The tool notes events that have no properties and nothing else, so look for them in the dry run, and remove those rows from the sheet. (A banner in the *property* column is refused: see the table below.)
- **Options that differ per tab.** `--map`, `--header-row`, `--fill-down` and the rest apply to every source in one run. Tabs whose headers differ need separate runs.

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
| `2 columns could be 'description': B 'Description', E 'Description'` | Two columns with the same header | Pick by letter: `--map description=@E`, and drop the other with `--ignore-column @B` |
| `the property cell is 'N/A'` (or `-`, `none`, a list, `name (type)`) | Not a property name | Leave the cell empty, or put one property on each row |
| `'string[]' is a list` | A plan has no list types | Describe the items separately, or `--type-map 'string[]=string'` on purpose |
| `lists the values of an enum in the type cell` | `enum (a \| b)` | Put the values in the allowed-values column, and write just `enum` |
| `looks like notation, not a value` | `[a, b]`, `a (default)`, `etc.` in allowed values | Write plain values separated by a bar, comma, semicolon or line break |
| `has allowed values but its type is 'string'` | Values on a property that is not an enum | Write the type as `enum`, or clear the values |
| `required is '...', which is not a yes or a no` | A word not in the yes/no list | Change the cell (a checkbox gives TRUE or FALSE); the words are in `column-names.md` |
| `does not look like an access token` | The token has a space, a line break or a non-ASCII character | Set `GOOGLE_SHEETS_ACCESS_TOKEN` again to the bare token (it is never shown) |
| `the download was cut short` / `cut off or malformed` | The connection broke mid-answer | Run it again |
| `not shared by link` | The sheet needs a sign-in | Share it by link, set the token, or download the CSV |

Names are kept exactly as written. If your sheet says `Level Completed`, the plan says `Level Completed`, and the review rules (`NAM-001`, `NAM-002`) will tell you it is not `object_action` snake_case. The tool does not rename your events.

The sheet usually has no metrics, so the plan has none. That is fine for `propose`; proposed metrics are added next to your events.

## Limits and safety

- Only `https://docs.google.com/spreadsheets/...` addresses are accepted. The request addresses are built by the tool from the sheet's id, and a redirect is followed only inside Google's domains, and never when a token is attached.
- A sheet over 5 MB is refused, and so is reading more than 50 tabs in one run (`--all-tabs` on a sheet with more; name the tabs you need with `--tab`). A sheet with more than 50 tabs is fine when you name the tab or its `gid`.
- Hidden rows and columns are probably included; check with `--dry-run`.
- Cells are read as the text the sheet displays (formulas show their result).
- A token is checked before it is used: a space, a line break or a non-ASCII character in it is refused, and the message never shows the value.
- The tool reads; it never writes to your sheet.
