"""Create a private environment and start the app using the included PDF wheel."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent
VERSION = "6.21.4"


def main():
    if sys.version_info < (3, 11):
        print("Nainštaluj Python 3.11 alebo novší (odporúčaný Python 3.12).", file=sys.stderr)
        return 1
    root = BASE / ".venv"
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        if not python.is_file():
            print("Vytváram lokálne prostredie .venv…", flush=True)
            venv.EnvBuilder(with_pip=True).create(root)
        check = subprocess.run([str(python), "-c",
                                f"import pypdf; raise SystemExit(pypdf.__version__ != {VERSION!r})"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode:
            print("Inštalujem pribalenú knižnicu na čítanie PDF (offline)…", flush=True)
            subprocess.run([str(python), "-m", "pip", "--disable-pip-version-check", "install",
                            "--no-index", "--find-links", str(BASE / "vendor"),
                            "-r", str(BASE / "requirements.txt")], cwd=BASE, check=True)
        return subprocess.call([str(python), str(BASE / "app.py"), "--open", *sys.argv[1:]], cwd=BASE)
    except KeyboardInterrupt:
        return 0
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Spustenie zlyhalo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
