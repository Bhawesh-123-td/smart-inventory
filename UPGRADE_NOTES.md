# Smart Inventory v7+ Upgrade

This version targets a professional 7+/10 baseline.

## Added
- Business Center dashboard
- Period filters: All Time, Today, This Week, This Month, This Year
- Sales, purchases, expenses, COGS, net profit and cash-flow summary
- Current inventory valuation using weighted-average purchase cost
- Low-stock and near-expiry/expiry alert counts when the database has the relevant fields
- Product Control Center for stock/batch/expiry review when supported by the database
- Safer optional-column handling for older databases
- Import-safe `__main__` guard

## Compatibility
Existing database columns are not deleted or renamed. Optional fields are detected at runtime.
