"""Beacon journal logging via syslog.

All messages are tagged with identifier ``beacon`` so they can be viewed with::

    journalctl -t beacon
    journalctl -t beacon -f        # follow
    journalctl -t beacon --since today
"""

import syslog

_opened = False


def _ensure_open() -> None:
    global _opened
    if not _opened:
        syslog.openlog("beacon", syslog.LOG_PID, syslog.LOG_DAEMON)
        _opened = True


def info(msg: str) -> None:
    _ensure_open()
    syslog.syslog(syslog.LOG_INFO, msg)


def debug(msg: str) -> None:
    _ensure_open()
    syslog.syslog(syslog.LOG_DEBUG, msg)


def error(msg: str) -> None:
    _ensure_open()
    syslog.syslog(syslog.LOG_ERR, msg)
