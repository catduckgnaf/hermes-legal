"""Thin Hermes adapter. Loads tool definitions from a trusted local checkout
(HERMES_LEGAL_APP_DIR), opens the database read-only, never creates a missing
database, and reads keys only from Hermes — never from a secrets file."""
