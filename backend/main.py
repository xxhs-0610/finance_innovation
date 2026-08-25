"""RegTrust-RAG Standalone Backend Entry Point."""
from __future__ import annotations

import uvicorn
from app.api.main import app
from configs.settings import settings

if __name__ == "__main__":
    print("=" * 60)
    print("🏦 正在启动 RegTrust-RAG 银行监管与报表可信问答独立后端服务...")
    print(f"🌐 服务运行地址: http://{settings.server.host}:{settings.server.port}")
    print(f"📚 OpenAPI 接口文档: http://{settings.server.host}:{settings.server.port}/docs")
    print(f"📑 ReDoc 接口文档: http://{settings.server.host}:{settings.server.port}/redoc")
    print("=" * 60)
    uvicorn.run(app, host=settings.server.host, port=settings.server.port)
