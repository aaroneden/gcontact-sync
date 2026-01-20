"""
Entry point for running gcontact_sync as a module.

Usage:
    python -m gcontact_sync --help
    python -m gcontact_sync auth --account account1
    python -m gcontact_sync sync --dry-run
"""

from gcontact_sync.cli import cli

if __name__ == "__main__":
    cli()
