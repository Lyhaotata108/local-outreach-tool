"""
自动读取本地 .env 后再运行 scrape_leads.py。

用法示例：
python run_scrape.py --industry "massage spa" --city "Orlando" --state "FL" --limit 20
"""

from pathlib import Path
import os


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and value:
            os.environ.setdefault(key, value)


BASE_DIR = Path(__file__).resolve().parent
load_env_file(BASE_DIR / ".env")

from scrape_leads import main  # noqa: E402


if __name__ == "__main__":
    main()
