# Data Layout

本文档说明项目数据如何落位到仓库结构中。

## 目录约定

### 原始数据

```text
data/raw/
  qa/
    QA数据.xlsx
  nfra_page_attachments_500/
    *.xls / *.xlsx / *.doc / *.docx / *.pdf
```

说明：

1. `qa/` 放原始题库或标注问答
2. `nfra_page_attachments_500/` 放监管附件原始文件
3. 原始大文件默认本地保留，不直接提交到 Git

### 解析结果

```text
data/parsed/
  docs/
  tables/
  meta/
```

说明：

1. `docs/` 存放 Word/PDF/Doc 解析结果
2. `tables/` 存放 Excel 解析结果
3. `meta/` 存放文件级元信息

### 处理结果

```text
data/processed/
  chunks/
  kb/
  eval_ready/
```

说明：

1. `chunks/` 存放条款 chunk、表格 chunk
2. `kb/` 存放知识库、metadata db、索引映射
3. `eval_ready/` 存放清洗后的评测数据

## 当前接入状态

当前本地已完成：

1. `QA数据.xlsx` 接入到 `data/raw/qa/`
2. 500 份监管附件接入到 `data/raw/nfra_page_attachments_500/`
3. `parsed/` 和 `processed/` 子目录已经建立完成

## 团队协作约定

1. 模块 1 只写 `data/parsed/`
2. 模块 2 只写 `data/processed/`
3. 评测模块优先消费 `data/processed/eval_ready/`
4. 不要跨模块直接写彼此目录
