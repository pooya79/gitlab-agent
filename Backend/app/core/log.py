import logging
import sys
from colorama import Fore, Style, init as colorama_init

# Initialize colorama for Windows compatibility
colorama_init(autoreset=True)

# Color mapping for levels
LEVEL_COLORS = {
    "DEBUG": Fore.CYAN,
    "INFO": Fore.GREEN,
    "WARNING": Fore.YELLOW,
    "ERROR": Fore.RED,
    "CRITICAL": Fore.MAGENTA,
}


class DowngradeOTLPExportErrors(logging.Filter):
    """Logfire/OpenTelemetry exporters log every failed batch export at ERROR
    (e.g. ``Failed to export metrics batch code: 401, reason: Unknown token``
    when the token is missing/invalid). Monitoring is optional, so downgrade
    these to WARNING to avoid spamming the logs with errors."""

    def filter(self, record):
        if record.name.startswith("opentelemetry") and record.levelno >= logging.ERROR:
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


class ColorFormatter(logging.Formatter):
    def format(self, record):
        log_color = LEVEL_COLORS.get(record.levelname, "")
        reset_color = Style.RESET_ALL
        log_fmt = (
            f"{Fore.WHITE}[%(asctime)s]{reset_color} "
            f"{log_color}[%(levelname)s]{reset_color} "
            f"{Fore.CYAN}(%(filename)s:%(lineno)d){reset_color} "
            f"%(message)s"
        )
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def setup_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Log everything, handlers filter levels

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColorFormatter())
    console_handler.addFilter(DowngradeOTLPExportErrors())

    # Clear old handlers (avoid duplicate logs if imported twice)
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(console_handler)

    return logger


logger = setup_logger()
