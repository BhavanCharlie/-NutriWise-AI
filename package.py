"""Build the submission zip without leaking secrets or personal data.

    python package.py   ->  ../NutriWise-AI-submission.zip
"""

import fnmatch
import sys
import zipfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "NutriWise-AI-submission.zip"

EXCLUDE = [
    ".env", ".venv/*", ".claude/*", ".git/*",
    "*__pycache__*", ".pytest_cache/*", ".ipynb_checkpoints/*", "*.pyc", ".DS_Store",
    "data/meals.json", "data/*.tmp", "data/*.corrupt-*",
]


def files_to_package() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if path.is_file() and not any(fnmatch.fnmatch(rel, pattern) for pattern in EXCLUDE):
            files.append(path)
    return files


def find_leaked_keys(files: list[Path]) -> list[str]:
    """Look for the ACTUAL key values from .env inside the files we're about to ship."""
    secrets = [v for v in dotenv_values(ROOT / ".env").values() if v and len(v) >= 12]
    leaks = []
    for path in files:
        text = path.read_text(errors="ignore")
        if any(secret in text for secret in secrets):
            leaks.append(path.relative_to(ROOT).as_posix())
    return leaks


def main():
    files = files_to_package()
    leaks = find_leaked_keys(files)
    if leaks:
        sys.exit(f"Refusing to package: an API key from .env appears in {leaks}")

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, Path("nutriwise") / path.relative_to(ROOT))
        zf.writestr("nutriwise/data/.keep", "")  # keep the empty data/ folder

    print(f"Packaged {len(files)} files into {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB)")
    for path in files:
        print("  ", path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
