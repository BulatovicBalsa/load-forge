import re

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


def interpolate(template: str, ctx: dict[str, str]) -> str:
    s = template.strip().strip('"')

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in ctx:
            raise RuntimeError(f"Unknown variable in template: ${{{key}}}")
        return ctx[key]

    return _VAR_PATTERN.sub(repl, s)
