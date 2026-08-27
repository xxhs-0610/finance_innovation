"""Centralized Structured Logging Configuration for RegTrust-RAG.
Supports Dual-Channel Output:
1. Console stdout output with millisecond timestamps & module locations.
2. UTF-8 Rotating File logging (logs/app.log) preventing file overgrowth.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from configs.settings import settings

# Ensure stdout/stderr handle UTF-8 cleanly on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ANSI Color Codes for Terminal Output
class TerminalColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GRAY = "\033[90m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


class ColorFormatter(logging.Formatter):
    """Terminal Formatter with readable colorized levels and structured layouts."""

    LEVEL_COLORS = {
        logging.DEBUG: TerminalColors.BLUE,
        logging.INFO: TerminalColors.GREEN,
        logging.WARNING: TerminalColors.YELLOW,
        logging.ERROR: TerminalColors.RED,
        logging.CRITICAL: TerminalColors.RED + TerminalColors.BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        level_color = self.LEVEL_COLORS.get(record.levelno, TerminalColors.RESET)
        time_str = self.formatTime(record, "%Y-%m-%d %H:%M:%S")

        # Colorize parts
        timestamp = f"{TerminalColors.GRAY}[{time_str}]{TerminalColors.RESET}"
        level = f"{level_color}[{record.levelname:<5}]{TerminalColors.RESET}"
        module_path = f"{TerminalColors.CYAN}[{record.name}:{record.lineno}]{TerminalColors.RESET}"

        message = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        formatted = f"{timestamp} {level} {module_path} {message}"
        if record.exc_text:
            formatted += f"\n{TerminalColors.RED}{record.exc_text}{TerminalColors.RESET}"
        if record.stack_info:
            formatted += f"\n{self.formatStack(record.stack_info)}"
        return formatted


class PlainFileFormatter(logging.Formatter):
    """Clean Plaintext Formatter for persistent file logging."""

    def format(self, record: logging.LogRecord) -> str:
        time_str = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        formatted = f"[{time_str}] [{record.levelname:<5}] [{record.name}:{record.lineno}] {record.getMessage()}"
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            formatted += f"\n{record.exc_text}"
        if record.stack_info:
            formatted += f"\n{self.formatStack(record.stack_info)}"
        return formatted


_LOGGING_INITIALIZED = False


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[Path | str] = None,
    enable_console: Optional[bool] = None,
    enable_file: Optional[bool] = None,
) -> logging.Logger:
    """Initialize system-wide logging configuration."""
    global _LOGGING_INITIALIZED

    log_cfg = settings.logging
    log_level_str = (level or log_cfg.level).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    file_path = Path(log_file) if log_file else log_cfg.log_file
    console_on = enable_console if enable_console is not None else log_cfg.enable_console
    file_on = enable_file if enable_file is not None else log_cfg.enable_file

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers if already set to avoid duplication
    if _LOGGING_INITIALIZED:
        root_logger.handlers.clear()

    # 1. Console Handler
    if console_on:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(ColorFormatter())
        root_logger.addHandler(console_handler)

    # 2. Rotating File Handler
    if file_on:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                str(file_path),
                maxBytes=log_cfg.max_bytes,
                backupCount=log_cfg.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(PlainFileFormatter())
            root_logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Failed to initialize log file at {file_path}: {e}\n")

    # Mute noisy third-party loggers
    for noisy in ["urllib3", "httpx", "httpcore", "sentence_transformers", "transformers", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Align uvicorn loggers with our format if running inside uvicorn
    for uvicorn_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uv_logger = logging.getLogger(uvicorn_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    _LOGGING_INITIALIZED = True
    app_logger = logging.getLogger("app")
    app_logger.info(
        f"[START] 日志系统初始化完成 | 级别: {log_level_str} | 控制台: {console_on} | 文件日志: {file_path if file_on else '关闭'}"
    )
    return app_logger


def get_logger(name: str) -> logging.Logger:
    """Obtain a namespaced logger instance."""
    if not _LOGGING_INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
