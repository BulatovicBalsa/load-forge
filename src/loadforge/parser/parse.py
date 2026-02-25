from pathlib import Path

from .metamodel import build_metamodel
from ..model import TestFile


def parse_file(path: Path) -> TestFile:
    """
    Parses DSL file and returns typed TestFile model.
    """
    mm = build_metamodel()
    model: TestFile = mm.model_from_file(str(path))
    return model


def parse_str(text: str) -> TestFile:
    """
    Parses DSL string (used mainly in tests).
    """
    mm = build_metamodel()
    model: TestFile = mm.model_from_str(text)
    return model
