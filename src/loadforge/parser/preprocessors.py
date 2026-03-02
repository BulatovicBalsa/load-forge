from textx import get_children_of_type, TextXSemanticError
from loadforge.model import ExpectJson, JsonCheckKind


def convert_json_check_kind_to_enum(model, _) -> None:
    for ex in get_children_of_type(ExpectJson, model):
        kind = ex.check.kind
        if isinstance(kind, str):
            ex.check.kind = JsonCheckKind(kind)
