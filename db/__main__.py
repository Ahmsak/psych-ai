"""Allow ``python -m psychai.db`` style invocation (alias for db.cli)."""

from db.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
