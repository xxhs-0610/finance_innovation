from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.parsing.config import (
    DatabaseConfig,
    external_source_dir_from_env,
    input_dir_from_env,
    output_paths,
)
from app.parsing.database import ParsingDatabase
from app.parsing.inventory import iter_source_files
from app.parsing.service import (
    dependency_status,
    export_jsonl,
    export_table_evidence,
    inventory_and_store,
    run_parse,
    sync_raw_files,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Module-1 regulatory document parsing pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check paths, dependencies, and MySQL connectivity")
    check.add_argument("--input-dir", type=Path, default=None)

    init_db = subparsers.add_parser("init-db", help="Create the parsing database and tables")
    init_db.add_argument("--show-tables", action="store_true")

    sync = subparsers.add_parser("sync-raw", help="Copy external source files into data/raw")
    sync.add_argument("--source", type=Path, default=None)
    sync.add_argument("--target", type=Path, default=None)

    inventory = subparsers.add_parser("inventory", help="Hash source files and write the generated manifest")
    inventory.add_argument("--input-dir", type=Path, default=None)

    parse = subparsers.add_parser("parse", help="Parse source files and persist normalized records")
    parse.add_argument("--input-dir", type=Path, default=None)
    parse.add_argument("--all", action="store_true", help="Parse all pending or changed files")
    parse.add_argument("--force", action="store_true", help="Reparse files even when unchanged")
    parse.add_argument("--retry-failed", action="store_true", help="Only retry failed or partial files")
    parse.add_argument("--limit", type=int, default=None)
    parse.add_argument("--file-type", action="append", choices=["doc", "docx", "pdf", "xls", "xlsx"])
    parse.add_argument("--doc-id", action="append", help="Parse one or more explicit stable doc_id values")
    parse.add_argument("--export-jsonl", action="store_true")

    export = subparsers.add_parser("export-jsonl", help="Export MySQL records to JSONL contracts")
    export.add_argument(
        "--include-cell-archive",
        action="store_true",
        help="Also regenerate the large parsed_tables.jsonl cell archive",
    )
    export.add_argument("--max-cells-per-evidence", type=int, default=20)
    subparsers.add_parser("report", help="Generate the module-1 parsing quality report")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = DatabaseConfig.from_env()
    database = ParsingDatabase(config)

    if args.command == "sync-raw":
        source = (args.source or external_source_dir_from_env()).resolve()
        target = (args.target or input_dir_from_env()).resolve()
        result = sync_raw_files(source, target)
        print(json.dumps({"source": str(source), "target": str(target), **result}, ensure_ascii=False, indent=2))
        return

    if args.command == "check":
        input_dir = (args.input_dir or input_dir_from_env()).resolve()
        db_status = database.check()
        result = {
            "input_dir": str(input_dir),
            "input_exists": input_dir.exists(),
            "input_files": len(list(iter_source_files(input_dir))) if input_dir.exists() else 0,
            "database": db_status,
            "dependencies": dependency_status(),
            "outputs": {key: str(value) for key, value in output_paths().items()},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "init-db":
        database.init_database()
        print(json.dumps(database.check(), ensure_ascii=False, indent=2))
        return

    if args.command == "inventory":
        input_dir = (args.input_dir or input_dir_from_env()).resolve()
        _, summary = inventory_and_store(input_dir, database)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "parse":
        input_dir = (args.input_dir or input_dir_from_env()).resolve()
        result = run_parse(
            input_dir,
            database,
            force=args.force,
            retry_failed=args.retry_failed,
            limit=args.limit,
            file_types=set(args.file_type or []),
            doc_ids=set(args.doc_id or []),
        )
        if args.export_jsonl:
            result["exports"] = export_jsonl(database, include_cell_archive=False)
            result["table_evidence"] = export_table_evidence(database)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "export-jsonl":
        result = {"table_evidence": export_table_evidence(database, args.max_cells_per_evidence)}
        result["module_contract"] = export_jsonl(database, include_cell_archive=False)
        if args.include_cell_archive:
            result["archive_exports"] = export_jsonl(database)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "report":
        path, data = write_report(database)
        print(json.dumps({"report": str(path), **data}, ensure_ascii=False, indent=2, default=str))
        return


if __name__ == "__main__":
    main()
