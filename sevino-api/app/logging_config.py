import logging
import sys

import structlog
from structlog.dev import BRIGHT, GREEN, RED, RESET_ALL, YELLOW

_UPPERCASE_LEVEL_STYLES = {
    "CRITICAL": RED + BRIGHT,
    "EXCEPTION": RED + BRIGHT,
    "ERROR": RED + BRIGHT,
    "WARN": YELLOW + BRIGHT,
    "WARNING": YELLOW + BRIGHT,
    "INFO": GREEN + BRIGHT,
    "DEBUG": GREEN + BRIGHT,
    "NOTSET": RED + BRIGHT,
}


def _uppercase_level(
    logger: object, method_name: str, event_dict: dict,
) -> dict:
    """Uppercase the log level to match uvicorn's style."""
    if "level" in event_dict:
        event_dict["level"] = event_dict["level"].upper()
    return event_dict


def _colorize_status(
    logger: object, method_name: str, event_dict: dict,
) -> dict:
    """Color-code the HTTP status code for dev console."""
    status = event_dict.get("status")
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return event_dict
    if code < 300:
        color = GREEN + BRIGHT
    elif code < 400:
        color = YELLOW + BRIGHT
    else:
        color = RED + BRIGHT
    event_dict["status"] = f"{color}{code}{RESET_ALL}"
    return event_dict


def _drop_console_noise(
    logger: object, method_name: str, event_dict: dict,
) -> dict:
    """Remove verbose fields that clutter the dev console."""
    event_dict.pop("timestamp", None)
    event_dict.pop("logger", None)
    event_dict.pop("logger_name", None)
    event_dict.pop("user_agent", None)
    event_dict.pop("ip", None)
    return event_dict


def configure_logging(environment: str) -> None:
    """Configure structlog + stdlib logging.

    Dev: colored console output (structlog.dev.ConsoleRenderer).
    Prod/Staging: JSON output for Railway log aggregation.
    """

    if environment == "dev":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            sort_keys=False,
            level_styles=_UPPERCASE_LEVEL_STYLES,
        )
        dev_filter: list[structlog.types.Processor] = [_drop_console_noise, _colorize_status]
    else:
        renderer = structlog.processors.JSONRenderer()
        dev_filter = []

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Processes stdlib log records (uvicorn, sqlalchemy, etc.)
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ExtraAdder(),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _uppercase_level,
            *dev_filter,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Our middleware provides richer access logging; silence uvicorn's to avoid duplicates
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
