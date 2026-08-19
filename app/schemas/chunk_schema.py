from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ChunkType = Literal["clause", "table"]


@dataclass
class SourceInfo:
    doc_id: str
    title: str = ""
    issuer: str = ""
    publish_date: str = ""
    source_url: str = ""
    local_path: str = ""
    section_path: list[str] = field(default_factory=list)
    clause_no: str = ""
    sheet_name: str = ""
    table_name: str = ""
    cell_ref: str = ""


@dataclass
class KnowledgeChunk:
    chunk_id: str
    chunk_type: ChunkType
    doc_id: str
    text: str
    retrieval_text: str
    source: SourceInfo
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "title": self.source.title,
                "issuer": self.source.issuer,
                "publish_date": self.source.publish_date,
                "source_url": self.source.source_url,
                "local_path": self.source.local_path,
                "section_path": self.source.section_path,
                "clause_no": self.source.clause_no,
                "sheet_name": self.source.sheet_name,
                "table_name": self.source.table_name,
            }
        )
        return data


@dataclass
class SearchResult:
    chunk_id: str
    chunk_type: ChunkType
    score: float
    text: str
    source: SourceInfo
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
