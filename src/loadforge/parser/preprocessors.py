from textx import get_children_of_type
from loadforge.model import AuthLogin, ExpectJson, HttpMethod, JsonCheckKind, Request


def convert_json_check_kind_to_enum(model, _) -> None:
    for ex in get_children_of_type(ExpectJson, model):
        kind = ex.check.kind
        if isinstance(kind, str):
            ex.check.kind = JsonCheckKind(kind)


def convert_http_methods_to_enum(model, _) -> None:
    for req in get_children_of_type(Request, model):
        method = req.method
        if isinstance(method, str):
            req.method = HttpMethod(method)

    for auth in get_children_of_type(AuthLogin, model):
        method = auth.method
        if isinstance(method, str):
            auth.method = HttpMethod(method)
