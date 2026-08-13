# Frontend Plan

## 当前结论

当前仓库主体是后端与离线处理骨架，已经具备这些模块：

1. `app/parsing/`
2. `app/indexing/`
3. `app/retrieval/`
4. `app/generation/`
5. `app/api/`

此前缺失的是比赛展示所需的前端界面。

## 当前补充

已新增：

1. `frontend/app.py`
2. `frontend/README.md`
3. `requirements.txt` 中的 `streamlit`

## 为什么先选 Streamlit

1. 上手快，适合比赛 MVP
2. 不需要再单独维护 Node/React 工程
3. 能很快展示“答案 + 证据 + 风险提示”
4. 后续若需要更完整的产品形态，再升级成 React 即可

## 前端在赛题中的作用

比赛不只是交脚本，还需要一个能演示的系统界面。前端至少要承载：

1. 问题输入
2. 答案输出
3. 证据来源展示
4. 风险提示或拒答结果
5. 后续扩展原文定位与 QA 回放

## 后续建议

如果后端同学继续完善 `app.api.main.ask()` 或升级为 FastAPI 路由，前端无需重写，只需把调用方式从本地函数改成 HTTP 请求即可。
