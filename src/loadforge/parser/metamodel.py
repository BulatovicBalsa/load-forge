from pathlib import Path
from textx import metamodel_from_file
from loadforge.model import ExpectStatus, Scenario, ValueOrRef, VarEntry, VariablesBlock, Target, Ref, EnvCall, EnvVar, \
    Test, TestFile, Environment, Load, Request, Duration, AuthLogin, BodyBlock, BodyField, ExpectJson, JsonCheck, \
    MetricsBlock, MetricExpectation, UserListFile, UserEntry
from loadforge.parser.preprocessors import (
    convert_http_methods_to_enum,
    convert_json_check_kind_to_enum,
)

HERE = Path(__file__).resolve().parent.parent
GRAMMAR_PATH = HERE / "grammar" / "loadforge.tx"
USERLIST_GRAMMAR_PATH = HERE / "grammar" / "userlist.tx"


def build_metamodel():
    mm = metamodel_from_file(
        str(GRAMMAR_PATH),
        classes=[TestFile, Test,
            Environment, EnvVar, EnvCall,
            Ref, Target,
            VariablesBlock, VarEntry, ValueOrRef,
            Scenario, Request, ExpectStatus, ExpectJson, JsonCheck,
            Load, Duration,
            MetricsBlock, MetricExpectation,
            AuthLogin, BodyBlock, BodyField,
        ],
    )
    mm.register_model_processor(convert_json_check_kind_to_enum)
    mm.register_model_processor(convert_http_methods_to_enum)

    return mm


def build_userlist_metamodel():
    """Build a textX metamodel for parsing .ulf (User List File) files."""
    mm = metamodel_from_file(
        str(USERLIST_GRAMMAR_PATH),
        classes=[UserListFile, UserEntry],
    )
    return mm
