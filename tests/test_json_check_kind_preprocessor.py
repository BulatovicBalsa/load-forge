import pytest
import httpx

from loadforge.parser.parse import parse_str
from loadforge.model import ExpectJson, JsonCheckKind


DSL = r'''
test "t" {
  target "https://example.com"

  scenario "s" {
    request GET "/x"
    expect status 200
    expect json "$.results" isArray
  }
}
'''


def test_json_check_kind_is_enum_after_parse():
    model = parse_str(DSL)

    scenario = model.test.scenarios[0]
    expect_json_steps = [s for s in scenario.steps if isinstance(s, ExpectJson)]
    assert len(expect_json_steps) == 1

    step = expect_json_steps[0]
    assert isinstance(step.check.kind, JsonCheckKind)
    assert step.check.kind == JsonCheckKind.isArray