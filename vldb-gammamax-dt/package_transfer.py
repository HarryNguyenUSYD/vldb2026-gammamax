"""Package portable suite sources and cases without local builds or caches."""

import argparse
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parent
EXCLUDED = {"build", "__pycache__", ".venv", ".git", "compiled-oracles"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT.parent / f"{ROOT.name}-transfer.tar.gz")
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite {output}; choose another --output")
    output.parent.mkdir(parents=True, exist_ok=True)

    def include(info):
        parts = Path(info.name).parts[1:]
        if any(part in EXCLUDED for part in parts):
            return None
        if info.name.endswith((".pyc", ".exe", "-transfer.tar.gz")):
            return None
        return info

    with tarfile.open(output, "w:gz") as archive:
        archive.add(ROOT, arcname=ROOT.name, filter=include)
    print(output)


if __name__ == "__main__":
    main()
