from pathlib import Path
import sys


_CORE_SRC = str(Path(__file__).resolve().parents[2] / "src")
sys.path[:] = [_CORE_SRC, *(entry for entry in sys.path if entry != _CORE_SRC)]

from .cli import main  # noqa: E402

raise SystemExit(main())
