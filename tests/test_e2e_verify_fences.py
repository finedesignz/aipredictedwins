# tests/test_e2e_verify_fences.py
"""Phase 20 — the `scripts/e2e_verify.py` fences (cases 12-16, 42).

`scripts/e2e_verify.py` reads PRODUCTION. It must be SELECT-only, and read-only must be
a property of THE SCRIPT — not of how someone remembered to invoke it.

THREE INDEPENDENT LAYERS, because one is a convention and two are not:
  1. SELF-ENFORCED ENV — the script sets AIPW_DB_READONLY=1 BEFORE the first `src.db`
     import. **IMPORT ORDER IS LOAD-BEARING**: get_pool() latches `_pool` on FIRST CALL,
     and _create_pool() decides the libpq `options` (src/db.py:38) AND whether
     _bootstrap_schema() runs (:56) AT THAT MOMENT. Setting it after the import is
     setting it TOO LATE.
  2. SERVER-SIDE — that flag routes into `options=-c default_transaction_read_only=on`,
     so POSTGRES ITSELF refuses any mutation with SQLSTATE 25006.
  3. STATIC FENCE — this file, WITH a self-test (case 13) proving the fence FIRES.
     **A fence that has never failed is a fence nobody has tested.**

Case 42 closes the door NO COMMITTED-FILE GREP CAN SEE: `_tolerance()` reads os.environ
AT CALL TIME, so `RECONCILIATION_TOLERANCE_USD=100000` in Coolify would silently turn
BOTH the all-time row AND the window green. **A tolerance the evidence cannot see is a
tolerance that can be widened in secret.**

Zero network, zero DB, zero skips.
"""
import pathlib
import re
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_SCRIPT = _REPO / "scripts" / "e2e_verify.py"

# The mutation vocabulary. A SELECT-only script contains none of it.
_MUTATING = re.compile(
    r"\b(UPDATE\s+alpaca_trades|DELETE\s+FROM|INSERT\s+INTO|DROP\s+TABLE|ALTER\s+TABLE)\b",
    re.I,
)
# A knob that can manufacture a PASS.
_WIDENING_FLAG = re.compile(r"--(apply|write|fix|tolerance)", re.I)


def find_mutations(source: str) -> list[str]:
    """THE DETECTOR. Factored out at module level precisely so case 13 can PROVE it fires."""
    return [m.group(0) for m in _MUTATING.finditer(source)]


def find_widening_flags(source: str) -> list[str]:
    return [m.group(0) for m in _WIDENING_FLAG.finditer(source)]


def _script_src() -> str:
    assert _SCRIPT.exists(), "scripts/e2e_verify.py does not exist"
    return _SCRIPT.read_text(encoding="utf-8")


# ── case 13 — PROVE THE FENCE FIRES (passes BEFORE the script exists) ────────

def test_the_fence_actually_fires():
    """Case 13. Run the detector against a deliberately-MUTATING fixture and require
    that it REJECTS it. A fence that has never failed is a fence nobody has tested."""
    assert find_mutations("UPDATE alpaca_trades SET pnl = 0"), \
        "the SELECT-only detector cannot even see a bare UPDATE — it proves nothing"
    assert find_mutations("DELETE FROM alpaca_trades WHERE id = 1")
    assert find_mutations("INSERT INTO reconciliation_anchor VALUES (1)")

    # And it does NOT fire on a legitimate read.
    assert find_mutations("SELECT pnl FROM alpaca_trades WHERE bot_id = %s") == []

    # The widening-flag detector likewise fires, and likewise not on the allowed flags.
    assert find_widening_flags('ap.add_argument("--tolerance")')
    assert find_widening_flags('ap.add_argument("--apply", action="store_true")')
    assert find_widening_flags('ap.add_argument("--bot")') == []
    assert find_widening_flags('ap.add_argument("--json", action="store_true")') == []


# ── case 15 — the src/db.py guard e2e_verify RESTS ON (passes today) ─────────

def test_no_ddl_on_import_under_readonly():
    """Case 15. src/db.py:56's `if not _readonly():` guard on _bootstrap_schema().

    THIS IS THE GUARANTEE e2e_verify.py RESTS ON. If it regresses, the script silently
    writes DDL to prod on the first `src.db` import.
    """
    src = (_REPO / "src" / "db.py").read_text(encoding="utf-8")
    assert "_bootstrap_schema" in src, "positive control failed — the file moved"

    guard = re.search(
        r"if\s+not\s+_readonly\(\):\s*\n\s*_bootstrap_schema\(\)", src)
    assert guard, \
        "src/db.py no longer guards _bootstrap_schema() behind `if not _readonly():` — " \
        "a read-only analysis script would write DDL to PROD on import"

    # And the libpq option that Postgres itself enforces (SQLSTATE 25006).
    assert "default_transaction_read_only=on" in src


# ── case 12 — SELECT-ONLY, and no lever that could manufacture a PASS ────────

def test_e2e_verify_is_select_only():
    """Case 12. STATIC FENCE. RED until scripts/e2e_verify.py exists."""
    src = _script_src()

    # POSITIVE CONTROL FIRST — the scanned source is non-empty and is the right file.
    assert len(src) > 500, "positive control failed — the script is a stub"
    assert "reconcile" in src, "positive control failed — this is not the reconciliation script"

    assert find_mutations(src) == [], \
        f"scripts/e2e_verify.py issues MUTATING SQL: {find_mutations(src)}"
    assert find_widening_flags(src) == [], \
        f"scripts/e2e_verify.py declares a lever that could manufacture a PASS: " \
        f"{find_widening_flags(src)}"

    assert "apply=True" not in src, "the script can arm the backfill"
    assert "ensure_anchor" not in src, \
        "the script CREATES T0 — it would anchor the window to whenever someone ran it"


# ── case 14 — IMPORT ORDER IS THE GUARANTEE ─────────────────────────────────

def test_the_script_self_enforces_readonly_before_importing_src_db():
    """Case 14. AIPW_DB_READONLY must be SET at a source line STRICTLY BEFORE the first
    `src.` import. get_pool() latches _pool on FIRST CALL; setting the env after the
    import is setting it TOO LATE."""
    lines = _script_src().splitlines()

    readonly_at = next(
        (i for i, ln in enumerate(lines)
         if "AIPW_DB_READONLY" in ln and "=" in ln and not ln.strip().startswith("#")),
        None,
    )
    src_import_at = next(
        (i for i, ln in enumerate(lines)
         if re.match(r"\s*(from|import)\s+src[.\s]", ln)),
        None,
    )

    assert readonly_at is not None, "the script never sets AIPW_DB_READONLY"
    assert src_import_at is not None, "positive control failed — the script imports no src module"
    assert readonly_at < src_import_at, (
        f"AIPW_DB_READONLY is set at line {readonly_at + 1} but `src` is first imported at "
        f"line {src_import_at + 1} — the pool is already latched WRITABLE by then"
    )


# ── case 16 — INSUFFICIENT_SAMPLE IS NOT A PASS. NEITHER IS NO_ANCHOR. ──────

def _report(verdict, **over):
    r = {
        "tolerance_usd": 25.0, "tolerance_usd_source": "default",
        "tolerance_pct": 0.005, "tolerance_pct_source": "default",
        "tolerance_override": False,
        "bots": [{"bot_id": "A", "verdict": verdict}],
    }
    r.update(over)
    return r


def test_insufficient_sample_and_fail_both_exit_non_zero(monkeypatch):
    """Case 16. Exit 0 ONLY on an all-PASS report."""
    import scripts.e2e_verify as e2e

    assert set(e2e.VERDICTS) == {"PASS", "FAIL", "INSUFFICIENT_SAMPLE", "NO_ANCHOR"}

    monkeypatch.setattr(e2e, "build_report", lambda bot_ids=None: _report("PASS"))
    assert e2e.main(["--json"]) == 0

    for verdict in ("FAIL", "INSUFFICIENT_SAMPLE", "NO_ANCHOR"):
        monkeypatch.setattr(e2e, "build_report", lambda bot_ids=None, v=verdict: _report(v))
        rc = e2e.main(["--json"])
        assert rc != 0, f"{verdict} exited 0 — it was treated as a PASS"

    # A per-bot ERROR row also forces a non-zero exit.
    monkeypatch.setattr(
        e2e, "build_report",
        lambda bot_ids=None: _report("PASS", bots=[{"bot_id": "A", "error": "boom"}]),
    )
    assert e2e.main(["--json"]) != 0


# ── case 42 — THE LEVER CASE 24 CANNOT SEE ──────────────────────────────────

def test_an_env_tolerance_override_fails_loudly(monkeypatch, capsys):
    """Case 42. `_tolerance()` reads os.environ AT CALL TIME. Case 24 greps COMMITTED
    files and is therefore BLIND to a Coolify env var.

    `RECONCILIATION_TOLERANCE_USD=100000` would turn BOTH the all-time row AND the window
    green, and NOTHING in the committed evidence would show it. So the script must print
    the EFFECTIVE tolerance + its SOURCE, emit TOLERANCE_OVERRIDE, suppress every PASS,
    and exit NON-ZERO.
    """
    import scripts.e2e_verify as e2e

    # Provenance is REPORTED on the clean path.
    monkeypatch.delenv("RECONCILIATION_TOLERANCE_USD", raising=False)
    monkeypatch.delenv("RECONCILIATION_TOLERANCE_PCT", raising=False)
    prov = e2e.tolerance_provenance()
    assert prov["tolerance_usd"] == 25.0
    assert prov["tolerance_usd_source"] == "default"
    assert prov["tolerance_pct"] == 0.005
    assert prov["tolerance_pct_source"] == "default"
    assert prov["tolerance_override"] is False

    cases = [
        ("RECONCILIATION_TOLERANCE_USD", "100000", "tolerance_usd_source"),
        ("RECONCILIATION_TOLERANCE_PCT", "0.9", "tolerance_pct_source"),
    ]
    for var, value, source_key in cases:
        monkeypatch.delenv("RECONCILIATION_TOLERANCE_USD", raising=False)
        monkeypatch.delenv("RECONCILIATION_TOLERANCE_PCT", raising=False)
        monkeypatch.setenv(var, value)

        prov = e2e.tolerance_provenance()
        assert prov["tolerance_override"] is True
        assert prov[source_key] == "env"

        # The script must NOT grade against a tampered ruler. It must never reach prod,
        # never emit a PASS, and must exit non-zero.
        monkeypatch.setattr(
            e2e, "build_report",
            lambda bot_ids=None: pytest.fail(
                "the script queried PROD while a tolerance override was in effect"),
        )
        rc = e2e.main([])
        out = capsys.readouterr().out

        assert rc != 0, f"{var} override exited 0 — the breach was silently widened away"
        assert "TOLERANCE_OVERRIDE" in out, "the override is invisible in the evidence"
        assert "PASS" not in out, "a PASS was emitted while the tolerance was overridden"
