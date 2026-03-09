"""
User abstractions for load testing.

Provides a unified interface for user identity regardless of source
(static credentials from env/variables, or external CSV file).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from loadforge.model.auth import AuthLogin


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


@dataclass(frozen=True)
class User:
    """A single user identity with credentials and a human-readable label."""
    credentials: dict[str, str] = field(default_factory=dict)
    display_name: str = "anonymous"


@runtime_checkable
class UserSource(Protocol):
    """Protocol for objects that supply users to virtual-user coroutines."""

    @property
    def per_user_auth(self) -> bool:
        """True if each virtual user must authenticate individually."""
        ...

    def get_user(self, index: int) -> User:
        """Return the user assigned to virtual-user *index*."""
        ...

    def __len__(self) -> int:
        """Total number of distinct users available."""
        ...


class StaticUserSource:
    """
    A single shared user whose credentials come from the runtime context
    (environment variables / DSL variables).

    All virtual users share the same identity and token.
    """

    def __init__(self, ctx: dict[str, str]) -> None:
        self._user = User(credentials=dict(ctx), display_name="static")

    @property
    def per_user_auth(self) -> bool:
        return False

    def get_user(self, index: int) -> User:
        return self._user

    def __len__(self) -> int:
        return 1


class CsvUserSource:
    """
    Users loaded and validated from a CSV file.
    """

    def __init__(
        self,
        csv_path: str,
        base_dir: Path,
        auth: AuthLogin,
    ) -> None:
        required_columns = _extract_required_columns(auth)
        self._users = _load_and_validate_csv(csv_path, base_dir, required_columns)

    @property
    def per_user_auth(self) -> bool:
        return True

    def get_user(self, index: int) -> User:
        return self._users[index % len(self._users)]

    def __len__(self) -> int:
        return len(self._users)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_required_columns(auth: AuthLogin) -> set[str]:
    """
    Scan ``${placeholder}`` references in the auth body field values and
    return the set of column names the CSV must provide.
    """
    columns: set[str] = set()
    if auth.body is None:
        return columns
    for f in auth.body.fields:
        if f.value is None:
            continue
        raw = getattr(f.value, "value", "") or ""
        columns.update(_VAR_PATTERN.findall(raw))
    return columns


def _load_and_validate_csv(
    csv_path: str,
    base_dir: Path,
    required_columns: set[str],
) -> list[User]:
    """
    Load *csv_path* (relative to *base_dir* when not absolute), validate
    that all *required_columns* exist, and return a list of ``User`` objects.
    """
    path = Path(csv_path.strip().strip('"'))
    if not path.is_absolute():
        path = base_dir / path

    if not path.exists():
        raise FileNotFoundError(
            f"User data CSV file not found: {path}\n"
            f"Looking in: {base_dir}"
        )

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        if not reader.fieldnames:
            raise ValueError(f"CSV file has no header row: {path}")

        available = set(reader.fieldnames)
        missing = required_columns - available
        if missing:
            raise ValueError(
                f"CSV file is missing required column(s): {sorted(missing)}. "
                f"Available columns: {sorted(available)}. "
                f"File: {path}"
            )

        users: list[User] = []
        for row_num, row in enumerate(reader, start=2):
            cleaned = {key: value.strip() for key, value in row.items()}

            empty_fields = [key for key, value in cleaned.items() if not value]
            if empty_fields:
                raise ValueError(
                    f"Empty value(s) in CSV row {row_num} for column(s): "
                    f"{', '.join(empty_fields)}\nFile: {path}"
                )

            # Use first column value as the human-readable display name.
            display = next(iter(cleaned.values()), f"row-{row_num}")
            users.append(User(credentials=cleaned, display_name=display))

    if not users:
        raise ValueError(f"No user data found in CSV file: {path}")

    return users
