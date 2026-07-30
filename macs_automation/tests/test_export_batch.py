"""Tests for the batch → .frc export used by the MACS+ PDF replay."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "macs_automation/tests/fixtures/atlantic_park_run00000.frc"


def _load_module():
    path = REPO / "tools/macs_replay/export_batch.py"
    spec = importlib.util.spec_from_file_location("export_batch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export_batch = _load_module()


def _rows(dicts):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cols = list(dicts[0])
    conn.execute(f"CREATE TABLE runs ({', '.join(cols)})")
    conn.executemany(
        f"INSERT INTO runs VALUES ({', '.join('?' * len(cols))})",
        [tuple(d[c] for c in cols) for d in dicts],
    )
    return conn.execute("SELECT * FROM runs").fetchall()


class TestVaryingColumns:
    def test_detects_a_column_that_moves(self):
        rows = _rows([{"qf": 100.0, "span1": 7.5}, {"qf": 200.0, "span1": 7.5}])
        assert export_batch.varying_columns(rows) == ["qf"]

    def test_ignores_outputs(self):
        # uf_max varies on every batch and means nothing here.
        rows = _rows([{"qf": 100.0, "uf_max": 0.4}, {"qf": 100.0, "uf_max": 0.9}])
        assert export_batch.varying_columns(rows) == []

    def test_single_row_has_nothing_varying(self):
        rows = _rows([{"qf": 100.0, "span1": 7.5}])
        assert export_batch.varying_columns(rows) == []


def _make_db(tmp_path: Path, n: int = 3) -> Path:
    db = tmp_path / "results.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE batches (batch_id TEXT, name TEXT, frc_import_id TEXT)")
    conn.execute("CREATE TABLE frc_imports (id TEXT, xml TEXT)")
    conn.execute(
        "CREATE TABLE runs (id INTEGER, batch_id TEXT, sample_index INTEGER, "
        "error TEXT, qf REAL, window_percent REAL, uf_max REAL, span1 REAL)"
    )
    conn.execute("INSERT INTO frc_imports VALUES ('imp1', ?)", (FIXTURE.read_text(encoding="utf-8-sig"),))
    conn.execute("INSERT INTO batches VALUES ('b1', 'test', 'imp1')")
    for i in range(n):
        conn.execute(
            "INSERT INTO runs VALUES (?, 'b1', ?, NULL, ?, ?, 0.5, 7.5)",
            (i + 1, i, 100.0 + i, 10.0 + i),
        )
    conn.commit()
    return db


def test_sampling_does_not_hide_varying_inputs(tmp_path, monkeypatch, capsys):
    """A --sample of 1 must still override the varying inputs.

    Deriving the varying set from the sample instead of the batch makes a
    varying input look fixed, so it is never overridden and every PDF silently
    carries the seed's value.
    """
    db = _make_db(tmp_path, n=3)
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        ["export_batch.py", "--db", str(db), "--batch-id", "b1",
         "--out", str(out), "--sample", "1", "--force"],
    )
    assert export_batch.main() == 0

    written = (out / "frc" / "run00000.frc").read_text(encoding="utf-8")
    # the run's own value, not the seed's 511
    assert 'Name="qf" Value="100"' in written
    assert 'Name="qf" Value="511"' not in written
    assert "qf" in capsys.readouterr().out


def test_exports_every_run_by_default(tmp_path, monkeypatch):
    db = _make_db(tmp_path, n=3)
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        ["export_batch.py", "--db", str(db), "--batch-id", "b1", "--out", str(out), "--force"],
    )
    assert export_batch.main() == 0
    assert len(list((out / "frc").glob("*.frc"))) == 3


def test_landing_tab_is_rewritten_away_from_fire(tmp_path, monkeypatch):
    db = _make_db(tmp_path, n=1)
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        ["export_batch.py", "--db", str(db), "--batch-id", "b1", "--out", str(out), "--force"],
    )
    export_batch.main()
    written = (out / "frc" / "run00000.frc").read_text(encoding="utf-8")
    assert 'Name="CurrentTab" Value="1"' in written


def test_refuses_a_seed_that_disagrees_with_the_batch(tmp_path, monkeypatch):
    db = _make_db(tmp_path, n=3)
    # span1 is fixed across the batch at 7.5; the fixture disagrees
    conn = sqlite3.connect(db)
    conn.execute("UPDATE runs SET span1 = 99.0")
    conn.commit()
    out = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        ["export_batch.py", "--db", str(db), "--batch-id", "b1", "--out", str(out)],
    )
    with pytest.raises(SystemExit, match="span1"):
        export_batch.main()
