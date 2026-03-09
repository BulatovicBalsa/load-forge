"""
User abstractions for load testing.

Provides a unified interface for user identity regardless of source
(static credentials from env/variables, or external .ulf file).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from loadforge.model.auth import AuthLogin
from loadforge.model.userlist import UserListFile


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


class UlfUserSource:
    """
    Users loaded and validated from a .ulf (User List File).

    The .ulf file uses the syntax ``username : password`` (one entry per line)
    and is parsed by textX using the ``userlist.tx`` grammar.
    """

    def __init__(
        self,
        ulf_path: Path,
        auth: AuthLogin,
    ) -> None:
        required_columns = _extract_required_columns(auth)
        self._users = _load_and_validate_ulf(ulf_path, required_columns)

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
    return the set of column names the user source must provide.
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


def _load_and_validate_ulf(
    path: Path,
    required_columns: set[str],
) -> list[User]:
    """
    Parse a ``.ulf`` file at the given *path* using textX and return a
    list of ``User`` objects.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"User list file not found: {path}\n"
            f"Looking in: {path.parent}"
        )

    # Validate that the auth body only references columns the .ulf provides
    available: set[str] = {"username", "password"}
    missing = required_columns - available
    if missing:
        raise ValueError(
            f"Auth body references variable(s) not available in .ulf format: "
            f"{sorted(missing)}. "
            f"The .ulf format provides: {sorted(available)}. "
            f"File: {path}"
        )

    # Parse the .ulf file using the textX userlist grammar
    from loadforge.parser.metamodel import build_userlist_metamodel

    mm = build_userlist_metamodel()
    try:
        model = mm.model_from_file(str(path))
    except Exception as exc:
        raise ValueError(
            f"Failed to parse user list file: {path}\n"
            f"Expected format: username : password (one per line)\n"
            f"Error: {exc}"
        ) from exc

    if not isinstance(model, UserListFile) or not model.entries:
        raise ValueError(f"No user entries found in user list file: {path}")

    users: list[User] = []
    for i, entry in enumerate(model.entries, start=1):
        username = entry.username.strip()
        password = entry.password.strip()

        if not username:
            raise ValueError(
                f"Empty username in entry {i} of user list file: {path}"
            )
        if not password:
            raise ValueError(
                f"Empty password in entry {i} of user list file: {path}"
            )

        users.append(
            User(
                credentials={"username": username, "password": password},
                display_name=username,
            )
        )

    return users
