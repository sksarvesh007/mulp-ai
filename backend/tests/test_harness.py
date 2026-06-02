from __future__ import annotations

from eval.harness import _conf_threshold, render_report, run_eval, write_report


async def test_run_eval_all_pass() -> None:
    outcomes = await run_eval()
    assert len(outcomes) == 12
    assert all(o.passed for o in outcomes), [o.mismatch for o in outcomes if not o.passed]


def test_conf_threshold_parsing() -> None:
    assert _conf_threshold("above 0.85") == 0.85
    assert _conf_threshold("above 0.90") == 0.90
    assert _conf_threshold(None) is None
    assert _conf_threshold("n/a") is None


async def test_render_and_write(tmp_path) -> None:
    outcomes = await run_eval()
    md = render_report(outcomes)
    assert "Eval Report" in md
    assert "TC001" in md and "Full trace" in md
    out = write_report(outcomes, tmp_path / "report.md")
    assert out.exists() and out.read_text().startswith("# Eval Report")
