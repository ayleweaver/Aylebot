import logging

logger = logging.getLogger()
handler = logging.StreamHandler()

log_fmtter = logging.Formatter(fmt=f"[%(asctime)s] [%(levelname)-8s] [%(name)s] %(msg)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(log_fmtter)
logger.setLevel(logging.INFO)
logger.addHandler(handler)