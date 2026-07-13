---
name: file-index-skill
description: 处理 LLM-WIKI 赛题中的文件索引。Use when 需要对 docs 目录执行 build_index、count_by_type、find_path、recall_candidates、summarize_index，建立统一文件元数据索引，统计指定后缀数量，查找文件路径，或为 Office、文本代码、知识问答任务召回候选文件。
---

# File Index Skill

本 Skill 是 `work/skills/file_index_agent.md` 背后的可执行能力层。文件索引Agent负责判断任务是否属于文件索引和候选召回，本 Skill 负责用确定性的 Python 脚本完成实际索引处理。

## 适用范围

处理 LLM-WIKI `docs/` 目录下的文件元数据：

- 构建统一文件索引
- 统计题目指定后缀数量
- 查找指定文件路径
- 按问题召回候选文件
- 汇总文件总数、后缀数量和一级目录数量

不要把本 Skill 用于 Office 正文解析、批注提取、代码 TODO 解析、知识问答生成或安全拒绝判定。它只处理路径和元数据，不读取业务文件正文。

## 依赖安装

本 Skill 只使用 Python 标准库，面向 Linux + Python 3 环境，不需要第三方依赖。

如后续补充 `requirements.txt`，也应保持为空或仅包含注释说明。

## CLI 调用

从提交作品根目录运行统一入口：

```bash
python work/skills/file_index_skill/scripts/file_index_agent_cli.py \
  --input-file payload.json \
  --output-file result.json
```

也可以传入行内 JSON：

```bash
python work/skills/file_index_skill/scripts/file_index_agent_cli.py \
  --input-json '{"task_type":"count_by_type","question_title":"doc文件的数量","wiki_root":"llm-wiki","safety":{"resource_checked":true}}'
```

自动化流程优先使用 `--input-file`，避免 shell 引号转义问题。

## 输入契约

输入必须是 JSON 对象：

```json
{
  "question_id": "group-1-6",
  "question_title": "doc文件的数量",
  "task_type": "build_index",
  "wiki_root": "llm-wiki",
  "docs_root": "llm-wiki/docs",
  "filters": {
    "extensions": ["doc", "docx"],
    "categories": ["05_需求设计"],
    "include_temp_files": true,
    "limit": 20
  },
  "safety": {
    "resource_checked": true
  },
  "run_log_dir": "logs/20260713_153000"
}
```

要求：

- `task_type` 必须是本 Skill 支持的任务类型。
- `safety.resource_checked` 必须为 `true`；否则 CLI 不扫描目录。
- `docs_root` 未传入时，默认使用 `{wiki_root}/docs`。
- 输出路径必须使用 LLM-WIKI 相对路径风格，例如 `docs/05_需求设计/example.docx`。

## 输出契约

CLI 始终向 stdout 输出 JSON 对象。如果设置了 `--output-file`，同一份 JSON 也会写入该文件。

成功输出结构：

```json
{
  "status": "ok",
  "task_type": "build_index",
  "answer": {},
  "summary": {},
  "files": [],
  "candidate_files": [],
  "logs": []
}
```

错误输出结构：

```json
{
  "status": "error",
  "task_type": "build_index",
  "answer": {
    "datas": []
  },
  "reason": "docs_root does not exist",
  "logs": []
}
```

文件索引Skill不生成 `{"error_msg":"高危命令，拒绝访问"}`。安全拒绝统一由安全守卫Agent或主控编排Agent处理。

## 支持任务

- `build_index`：扫描 `docs/`，写入并返回索引摘要。
- `count_by_type`：从问题或 `filters.extensions` 识别后缀并统计数量。
- `find_path`：从问题中识别文件名并返回匹配路径。
- `recall_candidates`：按确定性规则返回排序后的候选文件。
- `summarize_index`：返回文件总数、各后缀数量和各一级目录数量。

## 文件分类

题目统计枚举固定为：

```text
doc, docx, ppt, pptx, xls, xlsx, xml, java, py, html, md, js
```

Office 文件：

```text
doc, docx, ppt, pptx, xls, xlsx
```

文本代码文件：

```text
xml, java, py, html, md, js
```

其他后缀可以进入索引，但不参与文件类型数量统计，除非后续题目明确要求。

## 召回规则

候选文件召回应使用确定性轻量规则，不依赖大模型：

- 完整文件名命中：最高优先级。
- 主文件名命中：高优先级。
- 路径片段、目录名、后缀、关键词命中：逐级降权。
- 多个规则命中时可累加分数。
- 默认最多返回 20 个候选文件。

召回结果必须包含路径、后缀、文件类型、分数和命中原因，方便主控和下游 Agent 做审计。

## 安全规则

- 只在 `safety.resource_checked=true` 时扫描文件。
- 不扫描 `docs/` 之外的目录。
- 不读取文件正文。
- 不解析 Office、代码、宏或嵌入对象。
- 不执行任何命令。
- 不修改任何文件。
- 不访问网络。
- 只返回路径和元数据层面的索引结果。

## 日志

如果传入 `run_log_dir`，CLI 会追加写入：

- `file_index_agent.log`
- `file_index_agent_result.jsonl`
- `file_index.json`

日志内容包括任务类型、状态、索引摘要、候选文件数量、召回原因和异常信息。

## 脚本映射

- `scripts/file_index_agent_cli.py`：统一 CLI 入口。
- `scripts/file_index_common.py`：JSON 读写、路径归一化、日志、统一结果结构、后缀分类。
- `scripts/index_builder.py`：索引构建和复用。
- `scripts/recall_rules.py`：问题解析、后缀识别、路径查找和候选文件打分。
