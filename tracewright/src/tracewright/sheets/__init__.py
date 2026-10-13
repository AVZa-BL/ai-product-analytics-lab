"""Reading the tracking you already have from a spreadsheet: tables, column mapping, Google Sheets.

A sheet is read in three steps, each of which can be checked on its own:
`table.py` turns a CSV export or an API response into a `Table` (a header and rows with their
sheet row numbers), `layout.py` decides which column means what, and `values.py` cleans the
words people really write in cells. `google.py` is the only part that touches the network.
"""
