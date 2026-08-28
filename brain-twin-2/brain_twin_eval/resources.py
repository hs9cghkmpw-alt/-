from __future__ import annotations

import platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PeakRssReading:
    bytes: int | None
    method: str


def peak_rss_reading() -> PeakRssReading:
    """Return best-effort process peak RSS without adding a dependency.

    Windows uses GetProcessMemoryInfo/PeakWorkingSetSize. POSIX uses getrusage;
    Linux reports KiB while macOS reports bytes. Failure is non-fatal because
    quality evaluation must not become unavailable only because RSS telemetry is.
    """
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            psapi = ctypes.WinDLL("psapi")
            kernel32 = ctypes.WinDLL("kernel32")
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            ok = psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            )
            if not ok:
                return PeakRssReading(None, "windows GetProcessMemoryInfo unavailable")
            return PeakRssReading(int(counters.PeakWorkingSetSize), "windows PeakWorkingSetSize")
        except Exception as exc:  # telemetry must never fail a quality run
            return PeakRssReading(None, f"windows RSS unavailable: {type(exc).__name__}")

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return PeakRssReading(value, "getrusage ru_maxrss bytes")
        return PeakRssReading(value * 1024, "getrusage ru_maxrss KiB")
    except Exception as exc:  # pragma: no cover - platform dependent fallback
        return PeakRssReading(None, f"RSS unavailable: {type(exc).__name__}")
