import logging
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def setup_logging(level: int = logging.INFO) -> None:
    """Print this package's logs (NSE requests, cache use) to stderr, timestamped in IST.

    Safe to call repeatedly (Streamlit re-runs the app script on every interaction).
    """
    logger = logging.getLogger("premarket")
    logger.setLevel(level)
    if logger.handlers:
        return
    fmt = logging.Formatter("%(asctime)s IST %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = lambda ts: datetime.fromtimestamp(ts, _IST).timetuple()
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = False
