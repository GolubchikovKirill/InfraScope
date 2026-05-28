from __future__ import annotations

import logging
import platform
import re
import subprocess

logger = logging.getLogger(__name__)


def parse_arp_table() -> dict[str, str]:
    """Read the local ARP table with cross-platform fallback behavior."""
    result: dict[str, str] = {}
    system = platform.system()
    try:
        if system == "Linux":
            try:
                with open("/proc/net/arp") as file:
                    for line in file.readlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                            result[parts[0]] = parts[3].lower()
            except FileNotFoundError:
                pass

            if not result:
                try:
                    output = subprocess.run(
                        ["ip", "neigh"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    ).stdout
                    for line in output.splitlines():
                        parts = line.split()
                        if len(parts) >= 5 and parts[3] == "lladdr":
                            result[parts[0]] = parts[4].lower()
                except FileNotFoundError:
                    pass
        elif system == "Darwin":
            output = subprocess.run(
                ["arp", "-a"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in output.splitlines():
                match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-f:]+)", line, re.I)
                if match and match.group(2) != "(incomplete)":
                    result[match.group(1)] = match.group(2).lower()
        elif system == "Windows":
            output = subprocess.run(
                ["arp", "-a"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in output.splitlines():
                match = re.search(
                    r"(\d+\.\d+\.\d+\.\d+)\s+([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})",
                    line,
                    re.I,
                )
                if match:
                    result[match.group(1)] = match.group(2).replace("-", ":").lower()
    except Exception as exc:
        logger.debug("ARP table read (best-effort): %s", exc)
    return result
