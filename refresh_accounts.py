import subprocess
import sys
from pathlib import Path


def main():
    result = subprocess.run(
        [sys.executable, "tamilogin.py"],
        capture_output=True,
        text=True,
        check=True,
    )

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    cleaned = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            cleaned.append(f"{parts[0]},{parts[1]},{parts[2]}")

    target = Path(__file__).resolve().parent / "accounts.txt"
    target.write_text("# auto-generated from tamilogin.py\n" + "\n".join(cleaned) + "\n", encoding="utf-8")

    print(f"Wrote {len(cleaned)} accounts to {target}")


if __name__ == "__main__":
    main()
