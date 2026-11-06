"""Single shared logger for the whole module -- every stage (CBOM generation, report
generation, export, migrations) logs here. File handler only (no console handler), so it
stays quiet in a consuming application unless that application also attaches its own
handler to this same logger name.
"""

import logging
import os

import config

logger = logging.getLogger("cbom_reporting")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.FileHandler(os.path.join(config.LOGS_DIR, "report_generation.log"))
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
