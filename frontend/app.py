"""RegTrust-RAG Web Application Launcher.

This launcher starts the FastAPI backend server and serves the modern 3-column Web UI.
"""
from __future__ import annotations

from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True):
    import uvicorn
    from app.api.main import app

    print("=" * 60)
    print("🏦 正在启动 RegTrust-RAG 银行监管与报表可信问答服务 (FastAPI)...")
    print(f"🌐 本地 Web 服务地址: http://{host}:{port}")
    print(f"📚 API 接口文档地址: http://{host}:{port}/docs")
    print("=" * 60)

    if open_browser:
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()


