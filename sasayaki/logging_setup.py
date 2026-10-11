"""Rotating log file at <data dir>/logs/sasayaki.log. API keys are redacted."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import data_dir

_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_configured = False


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _KEY.sub("sk-ant-***", record.getMessage())
        record.args = ()
        return True


def log_path() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sasayaki.log"


def setup_logging() -> Path:
    global _configured
    path = log_path()
    if _configured:
        return path
    _configured = True
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(_Redact())
    root = logging.getLogger("sasayaki")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.info("---- Sasayaki started ----")
    return path
