"""Preflight checks for the Synthea healthcare experiments.

Verifies that the three runtime layers required by exp1 / exp2 are actually
reachable on the current host:
    1. Neo4j bolt connection + schema setup (creates vector indexes if missing).
    2. SpacetimeDB bridge availability via TemporalBridge.from_env().
    3. FHIR loader can parse a handful of Synthea patients off the tarball.

Each check runs independently and prints a single [OK] / [FAIL] line so the
output stays easy to grep. A non-zero exit code means at least one layer is
not runnable — do not proceed to ingestion until all three pass.

Usage:
    python scripts/preflight_checks.py

Env vars consumed:
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD        — neo4j check
    STDB_URI, STDB_BINDINGS_MODULE, STDB_TOKEN    — spacetimedb check
    SYNTHEA_DATA_DIR (optional)                   — overrides default FHIR path
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Allow running from the repo root without installing the package
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


def _status(label: str, ok: bool, detail: str = "") -> None:
    """Print a one-line status marker for a preflight check.

    Args:
        label: Short name for the check (neo4j / spacetimedb / fhir_loader).
        ok: True if the check passed.
        detail: Optional single-line detail appended after the marker.
    """
    marker = "[OK]  " if ok else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"{marker} {label}{suffix}")


def _load_dotenv() -> None:
    """Load .env from the repo root into os.environ (no external dep).

    The bash wrappers source .env before calling the Python entry points,
    but on Windows PowerShell we do it here so the preflight works identically
    regardless of shell.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Do not clobber values the user already exported in the shell.
        os.environ.setdefault(key, value)


def check_neo4j() -> bool:
    """Verify Neo4j is reachable and the expected schema is in place.

    Runs ConnectionManager.setup_database() which creates the required vector
    indexes (including healthcare_embeddings) if they do not exist. Also
    executes a trivial RETURN 1 query to confirm the session works end-to-end.

    Returns:
        True if the bolt handshake + schema setup + test query all succeed.
    """
    try:
        from agentic_memory.core.connection import ConnectionManager
    except Exception as exc:  # noqa: BLE001
        _status("neo4j", False, f"import error: {exc}")
        return False

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    missing = [k for k, v in [("NEO4J_URI", uri), ("NEO4J_USER", user), ("NEO4J_PASSWORD", password)] if not v]
    if missing:
        _status("neo4j", False, f"missing env: {', '.join(missing)}")
        return False

    cm = None
    try:
        cm = ConnectionManager(uri, user, password)
        cm.setup_database()
        with cm.session() as session:
            rec = session.run("RETURN 1 AS ok").single()
            if not rec or rec["ok"] != 1:
                _status("neo4j", False, "RETURN 1 did not return 1")
                return False
        _status("neo4j", True, f"{uri} reachable; schema ensured")
        return True
    except Exception as exc:  # noqa: BLE001
        _status("neo4j", False, f"{type(exc).__name__}: {exc}")
        return False
    finally:
        if cm is not None:
            try:
                cm.close()
            except Exception:
                pass


def check_spacetimedb() -> bool:
    """Verify the TemporalBridge can talk to the SpacetimeDB helper.

    TemporalBridge.from_env() reads STDB_URI / STDB_BINDINGS_MODULE / STDB_TOKEN
    and checks that the Node helper script and bindings exist. is_available()
    performs that sanity check without making a network call; we then issue a
    tiny retrieve() to prove the RPC actually works end-to-end.

    Returns:
        True if the bridge reports available AND a round-trip retrieve call
        returns a well-formed payload.
    """
    try:
        from agentic_memory.temporal.bridge import TemporalBridge
    except Exception as exc:  # noqa: BLE001
        _status("spacetimedb", False, f"import error: {exc}")
        return False

    bridge = TemporalBridge.from_env()
    if not bridge.is_available():
        _status("spacetimedb", False, f"bridge unavailable: {bridge.disabled_reason}")
        return False

    # Attempt a harmless retrieve against a dummy project. Even if no claims
    # exist, the helper should return an empty result envelope rather than
    # raise — that proves process spawn + RPC parse are wired correctly.
    try:
        result = bridge.retrieve(
            project_id="preflight-smoke",
            seed_entities=[{"kind": "patient", "name": "__preflight_nonexistent__"}],
            half_life_hours=168.0,
            max_edges=1,
            max_hops=1,
        )
    except Exception as exc:  # noqa: BLE001
        _status("spacetimedb", False, f"retrieve() failed: {type(exc).__name__}: {exc}")
        return False

    edges = result.get("edges") if isinstance(result, dict) else None
    if edges is None:
        _status("spacetimedb", False, f"unexpected retrieve payload: {result!r}")
        return False

    _status("spacetimedb", True, f"bridge ok; retrieve returned {len(edges)} edges")
    return True


def check_fhir_loader() -> bool:
    """Verify SyntheaFHIRLoader can parse a handful of patients from disk.

    Loads at most 5 patients from the configured tarball, then streams records
    and counts record types. This catches FHIR↔CSV column-mapping drift before
    we spend 30+ minutes on a real ingest that would silently skew ground truth.

    Returns:
        True if the loader yields a non-empty patient lookup and at least one
        record. The record type mix is printed in the detail line so a human
        can spot-check it.
    """
    data_dir = os.getenv(
        "SYNTHEA_DATA_DIR",
        r"G:/My Drive/kubuntu/agentic-memory/big-healtcare-data/synthetic-data/synthea_2017_02_27.tar.gz",
    )
    if not Path(data_dir).exists():
        _status("fhir_loader", False, f"data path not found: {data_dir}")
        return False

    try:
        from agentic_memory.healthcare.fhir_loader import SyntheaFHIRLoader
    except Exception as exc:  # noqa: BLE001
        _status("fhir_loader", False, f"import error: {exc}")
        return False

    try:
        loader = SyntheaFHIRLoader(data_dir, max_patients=5)
        patients = loader.load_patient_lookup()
        if not patients:
            _status("fhir_loader", False, "patient lookup empty")
            return False

        # Reset loader to iterate from the top; fhir_loader is single-pass.
        loader2 = SyntheaFHIRLoader(data_dir, max_patients=5)
        type_counts: dict[str, int] = {}
        total = 0
        for row in loader2.iter_records():
            rtype = row.get("record_type", "unknown")
            type_counts[rtype] = type_counts.get(rtype, 0) + 1
            total += 1
            if total >= 200:  # cap so preflight stays fast
                break

        if total == 0:
            _status("fhir_loader", False, "iter_records yielded zero rows")
            return False

        mix = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
        _status("fhir_loader", True, f"{len(patients)} patients, {total} records ({mix})")
        return True
    except Exception as exc:  # noqa: BLE001
        _status("fhir_loader", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def main() -> int:
    """Run all three preflight checks and return a process exit code.

    Returns:
        0 if every check passed, 1 otherwise.
    """
    # Force unbuffered stdout so each check prints as it completes.
    # On Windows PowerShell Python defaults to line-buffered, which means a
    # hung check produces zero visible output for minutes. Explicitly
    # reconfiguring the stream avoids that failure mode.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    _load_dotenv()
    print("Running Synthea experiment preflight checks...")
    print(f"  NEO4J_URI = {os.getenv('NEO4J_URI', '<unset>')}")
    print(f"  STDB_URI  = {os.getenv('STDB_URI', '<unset>')}")
    print()

    print("Checking neo4j...", flush=True)
    neo4j_ok = check_neo4j()
    print("Checking spacetimedb...", flush=True)
    stdb_ok = check_spacetimedb()
    print("Checking fhir_loader...", flush=True)
    fhir_ok = check_fhir_loader()
    results = [neo4j_ok, stdb_ok, fhir_ok]
    print()
    if all(results):
        print("All preflight checks passed. Safe to run ingest_synthea.py.")
        return 0
    print("Preflight failures above. Fix them before ingestion.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
