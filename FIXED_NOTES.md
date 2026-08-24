# Smart Inventory — Fixed & Refined Version

This build fixes every runtime error found in the previous package and adds
dedicated Excel exports for purchases and sales.

## Critical fixes
- App no longer crashes on launch (`_datetime` typo in chart-of-accounts seeding).
- Backup system works: `os` is now imported, so verified backups, pre-edit /
  pre-delete safety backups, startup/close backups and restores all function.
- Startup backup moved after the `backup()` definition (was called before it
  existed and silently skipped).
- Excel import and the quantity control work: `re` is now imported.
- "Excel Template" button works without openpyxl — the template is written with
  the app's built-in standard-library XLSX writer.
- Accounting Center works: journal posting and Record Payment no longer crash
  (`_datetime` fixed), and the historical journal backfill now actually runs.

## Refinements
- Save flows no longer show a misleading "Invalid entry" error after a
  successful save — backups are best-effort (`_safe_backup`) and never block
  or mask a committed transaction.
- Removed duplicate `delete_selected_*` definitions; deletes now use the safer
  shared path with verified pre-delete backup and reliable record-ID detection.
- Restore Backup now verifies backup integrity before and after restoring.
- The +/- quantity control (from QUANTITY_UPGRADE.md) is now actually wired
  into the Purchase and Sales entry/edit forms.
- Reports no longer has two buttons both named "Business Center" — the second
  is now "Business Dashboard".
- "Opening Stock" sheets are now correctly detected during Excel import, and
  the template includes AD/B.S. date columns so imports pass validation.
- Old Cash sales are migrated to fully-paid on first run.
- Removed unused openpyxl dependency from the build script.
- Removed leftover `__pycache__` artifacts from the package.

## New features
- "Export Purchases Excel" — detailed purchase register with totals
  (Reports page and Purchases page).
- "Export Sales Excel" — detailed sales register with per-sale COGS, profit
  and payment status, plus revenue/profit totals (Reports page and Sales page).

## Verified
- `py_compile` passes.
- Runtime smoke test passed: startup + manual verified backups, weighted-average
  COGS (Rs. 550 on a 10@100 + 10@120, sell 5 scenario), stock levels, XLSX
  output readable by openpyxl, double-entry journal posting, account balances,
  and AD <-> B.S. date round-trip conversion.
