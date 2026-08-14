from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any


SEQUENCE_RE = re.compile(r"^(?P<seq>\d{3})_(?P<rest>.+)$")
CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两0-9]+条(?:之[一二三四五六七八九十0-9]+)?")
DOCUMENT_NO_PATTERNS = [
    re.compile(r"[\u4e00-\u9fff]{0,12}[〔\[]\d{4}[〕\]][第]?[0-9一二三四五六七八九十百]+号"),
    re.compile(r"[\u4e00-\u9fff]{1,12}发[〔\[]\d{4}[〕\]]\d+号"),
]
DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<y>20\d{2})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})"),
]
ISSUER_NAMES = [
    "国家金融监督管理总局",
    "中国银行保险监督管理委员会",
    "中国银保监会",
    "中国银行业监督管理委员会",
    "中国银监会",
    "中国人民银行",
    "财政部",
    "国务院",
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_filename(path: Path) -> dict[str, Any]:
    stem = path.stem.strip()
    match = SEQUENCE_RE.match(stem)
    source_seq = int(match.group("seq")) if match else None
    rest = match.group("rest") if match else stem
    pieces = [piece.strip(" _") for piece in rest.split("_") if piece.strip(" _")]
    if len(pieces) >= 2:
        source_page_title = "_".join(pieces[:-1])
        attachment_title = pieces[-1]
    else:
        source_page_title = pieces[0] if pieces else rest
        attachment_title = pieces[0] if pieces else rest
    doc_id = f"nfra_att_{source_seq:03d}" if source_seq is not None else ""
    family_seed = source_page_title or attachment_title or stem
    family_id = "family_" + hashlib.sha256(family_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "source_seq": source_seq,
        "doc_id": doc_id,
        "source_page_title": source_page_title,
        "attachment_title": attachment_title,
        "title": attachment_title or source_page_title,
        "document_family_id": family_id,
    }


def extract_text_metadata(text: str, fallback_title: str = "") -> dict[str, Any]:
    compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    first_lines = compact.splitlines()[:12]
    title = next((line for line in first_lines if 2 <= len(line) <= 200), fallback_title)
    issuer = next((name for name in ISSUER_NAMES if name in compact[:5000]), "")
    document_no = ""
    for pattern in DOCUMENT_NO_PATTERNS:
        match = pattern.search(compact[:5000])
        if match:
            document_no = match.group(0)
            break
    publish_date = None
    publish_date_text = ""
    for pattern in DATE_PATTERNS:
        match = pattern.search(compact[:5000])
        if not match:
            continue
        try:
            publish_date = date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
            publish_date_text = match.group(0)
            break
        except ValueError:
            continue
    return {
        "title": title or fallback_title,
        "issuer": issuer,
        "document_no": document_no,
        "publish_date": publish_date,
        "publish_date_text": publish_date_text,
    }


def find_clause_no(text: str) -> str:
    match = CLAUSE_RE.match(text.strip()[:80])
    return match.group(0) if match else ""


def prefer_extracted_title(extracted: str, fallback: str) -> str:
    generic = {"附件", "附表", "目录", "正文", "通知", "表格"}
    candidate = extracted.strip()
    if len(candidate) < 4 or candidate in generic:
        return fallback
    return candidate


def detect_heading(text: str, style_name: str = "") -> int | None:
    style_match = re.search(r"Heading\s*(\d+)", style_name, re.IGNORECASE)
    if style_match:
        return int(style_match.group(1))
    stripped = text.strip()
    if re.match(r"^第[一二三四五六七八九十百]+[编章]", stripped):
        return 1
    if re.match(r"^[一二三四五六七八九十]+、", stripped):
        return 2
    if re.match(r"^[（(][一二三四五六七八九十0-9]+[）)]", stripped):
        return 3
    return None


def detect_period(*texts: str) -> str:
    joined = " ".join(text for text in texts if text)
    quarter = re.search(r"(20\d{2})年?第?([一二三四1234])季度", joined)
    if quarter:
        qmap = {"一": "1", "二": "2", "三": "3", "四": "4"}
        return f"{quarter.group(1)}Q{qmap.get(quarter.group(2), quarter.group(2))}"
    month = re.search(r"(20\d{2})年\s*(1[0-2]|[1-9])月", joined)
    if month:
        return f"{month.group(1)}-{int(month.group(2)):02d}"
    year = re.search(r"(20\d{2})年", joined)
    return year.group(1) if year else ""


def detect_unit(*texts: str) -> str:
    joined = " ".join(text for text in texts if text)
    match = re.search(r"单位\s*[：:]\s*([^\s，,；;。]{1,20})", joined)
    if match:
        return match.group(1)
    for unit in ("亿元", "万元", "元", "%", "百分点", "家", "户", "笔", "人"):
        if unit in joined:
            return unit
    return ""
