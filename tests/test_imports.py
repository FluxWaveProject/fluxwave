import pytest

import fluxwave
from fluxwave.__main__ import debug_info, main


def test_public_version() -> None:
    assert fluxwave.__version__ == "0.2.1"


def test_node_pool_starts_empty() -> None:
    pool = fluxwave.NodePool()

    assert pool.nodes == {}


def test_debug_info_contains_runtime_sections() -> None:
    info = debug_info()

    assert f"fluxwave: {fluxwave.__version__}" in info
    assert "Python:" in info
    assert "System:" in info
    assert "Java:" in info


def test_cli_version_prints_debug_info(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0

    output = capsys.readouterr().out
    assert f"fluxwave: {fluxwave.__version__}" in output
