"""Who exists, which clinics exist, and who may see which one.

Everything in this package is about *people and tenants*, never about calls.
Call traces stay JSONL files on the volume — writing them as they happen is
what lets the panel read a call live — and nothing here reads or writes one.

The four tables are the minimum that makes step 4 of PLATFORM.md true:
organisations (with their own Prosper credential), users, memberships and
sessions. See `db.py` for why they live in SQLite on the same volume.
"""
