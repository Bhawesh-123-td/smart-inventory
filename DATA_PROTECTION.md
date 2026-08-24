# Data Protection Upgrade

Priority upgrade focused on preventing accidental data loss/corruption.

- SQLite backup API instead of copying a live database file
- Backup integrity verification before a backup is accepted
- Atomic temporary-file -> final-backup creation
- Up to 50 timestamped restore points
- Verified restore: corrupt backups are rejected
- Automatic backup before purchase/sale edits
- Automatic backup before destructive deletes
- Data Protection Center with integrity status, backup count, manual backup and restore
- Existing transaction rollback/error handling retained
