"""Path resolution helpers for root and backend environments."""
from __future__ import annotations

from pathlib import Path


def resolve_path(rel_path: str | Path) -> Path:
    """Resolve a relative path checking root workspace, backend, and current working directory."""
    path_obj = Path(rel_path)
    if path_obj.is_absolute() and path_obj.exists():
        return path_obj

    # 1. Check relative to CWD
    if path_obj.exists():
        return path_obj.resolve()

    # 2. Check relative to workspace root (parent of backend/app)
    # File is at backend/app/utils/paths.py -> parents[3] is 比赛/
    try:
        ws_root = Path(__file__).resolve().parents[3]
        ws_candidate = ws_root / path_obj
        if ws_candidate.exists():
            return ws_candidate
    except Exception:
        pass

    # 3. Check relative to finance_innovation or backend dir
    try:
        backend_root = Path(__file__).resolve().parents[2]
        backend_candidate = backend_root / path_obj
        if backend_candidate.exists():
            return backend_candidate
    except Exception:
        pass

    # 4. Check relative to finance_innovation
    try:
        fi_candidate = Path(__file__).resolve().parents[3] / "finance_innovation" / path_obj
        if fi_candidate.exists():
            return fi_candidate
    except Exception:
        pass

    return path_obj
