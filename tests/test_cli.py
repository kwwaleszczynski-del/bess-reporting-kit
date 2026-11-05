from pathlib import Path

from bess_report.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_technical_nem_command(tmp_path):
    rc = main(["technical", "--nem-slice", str(ROOT / "data/example/nem"), "--duid", "RANGEB1",
               "--site", str(ROOT / "config/site.example.yaml"), "--out", str(tmp_path)])
    assert rc == 0 and (tmp_path / "technical-nem.html").exists() and (tmp_path / "technical-nem.xlsx").exists()


def test_financial_command(tmp_path):
    rc = main(["financial", "--settlement", str(ROOT / "results/settlement.csv"), "--budget", str(ROOT / "results/budget.csv"),
               "--site", str(ROOT / "config/site.example.yaml"), "--out", str(tmp_path)])
    assert rc == 0 and (tmp_path / "financial-user.html").exists()


def test_readme_check_passes():
    assert main(["readme", "--root", str(ROOT), "--check"]) == 0
