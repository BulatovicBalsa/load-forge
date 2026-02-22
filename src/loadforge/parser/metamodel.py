from pathlib import Path
from textx import metamodel_from_file
from loadforge.model import ExpectStatus, Scenario, ValueOrRef, VarEntry, VariablesBlock, Target, Ref, EnvCall, EnvVar, \
    Test, TestFile, Environment, Load, Request, Duration

HERE = Path(__file__).resolve().parent.parent
GRAMMAR_PATH = HERE / "grammar" / "loadforge.tx"


def build_metamodel():
    return metamodel_from_file(
        str(GRAMMAR_PATH),
        classes=[TestFile, Test,
            Environment, EnvVar, EnvCall,
            Ref, Target,
            VariablesBlock, VarEntry, ValueOrRef,
            Scenario, Request, ExpectStatus,
            Load, Duration],
    )
