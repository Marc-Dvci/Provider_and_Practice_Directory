from __future__ import annotations

import json

from directory_pipeline.cli import main


def test_run_json_single_record(capsys):
    rc = main(["run", "--offline", "--json", "--record", "HL_005"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["provider_id"] == "HL_005"
    assert payload[0]["recommended_action"] == "no_change"


def test_run_unknown_record_returns_error(capsys):
    rc = main(["run", "--offline", "--json", "--record", "NOPE"])
    assert rc == 2


def test_backtest_command(capsys):
    rc = main(["backtest"])
    assert rc == 0
    assert "AUTO-UPDATE precision" in capsys.readouterr().out
