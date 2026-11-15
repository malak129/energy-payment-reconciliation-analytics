"""Start and stop only this probe's loopback/read-only Streamlit child process."""

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    acceptance = json.loads((ROOT / "outputs/phase7/acceptance.json").read_text())
    database = Path(acceptance["root"]) / "500/isolated.sqlite3"
    assert (
        database.is_file() and database.resolve() != (ROOT / "data/phase4-demo.sqlite3").resolve()
    )
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "src/energy_reconciliation/dashboard/app.py"),
        "--server.address=127.0.0.1",
        "--server.port=8507",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--",
        "--database",
        str(database),
        "--read-only",
    ]
    start = time.perf_counter()
    with (ROOT / "outputs/phase7/server.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=log, cwd=ROOT)
        try:
            while time.perf_counter() - start < 30:
                if child.poll() is not None:
                    raise RuntimeError("Streamlit exited before health check")
                try:
                    with urlopen("http://127.0.0.1:8507/_stcore/health", timeout=1) as response:
                        assert response.read() == b"ok"
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Streamlit health deadline exceeded")
            result = {
                "health": "ok",
                "startup_seconds": time.perf_counter() - start,
                "bind": "127.0.0.1:8507",
                "database": str(database),
                "read_only": True,
            }
            (ROOT / "outputs/phase7/server-probe.json").write_text(json.dumps(result, indent=2))
            print(result)
        finally:
            child.terminate()
            child.wait(timeout=15)


if __name__ == "__main__":
    main()
