"""
Model classes for the User List File (.ulf) format.

A .ulf file contains virtual user credentials with the syntax:

    username : password

One entry per line, parsed by textX using the userlist.tx grammar.
"""
from dataclasses import dataclass, field

from loadforge.model.base import TxNode


@dataclass
class UserEntry(TxNode):
    """A single user credential pair from a .ulf file."""
    username: str = ""
    password: str = ""


@dataclass
class UserListFile(TxNode):
    """Root model representing a parsed .ulf file."""
    entries: list[UserEntry] = field(default_factory=list)