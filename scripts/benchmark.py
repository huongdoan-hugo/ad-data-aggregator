"""Run aggregator.py in a separate process and append its time and peak memory to a log.

Windows only (peak memory comes from GetProcessMemoryInfo through ctypes).

Limitation: only the process started here is measured. If aggregator.py ever starts worker
processes, their memory is NOT included in the peak figures, so the real peak is higher.
Wall time still covers the whole run, workers included.

Arguments this script does not know are passed on to aggregator.py:
    python scripts\\benchmark.py --input data\\ad_data.csv --output results
"""

import argparse
import ctypes
import datetime
import os
import platform
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import NamedTuple, Optional

AGGREGATOR = Path(__file__).resolve().parent.parent / "aggregator.py"
DEFAULT_LOG = Path(__file__).resolve().parent.parent / "benchmark.log"
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
BYTES_PER_MB = 1024 * 1024


class ProcessMemoryCounters(ctypes.Structure):
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


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PeakMemory(NamedTuple):
    working_set: int
    pagefile: int


class Measurement(NamedTuple):
    return_code: int
    seconds: float
    peak_memory: Optional[PeakMemory]
    output: str


def load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.K32GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    return kernel32


def read_peak_memory(kernel32, handle):
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return PeakMemory(counters.PeakWorkingSetSize, counters.PeakPagefileUsage)


def total_physical_memory(kernel32):
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullTotalPhys


def measure(kernel32, command):
    """Run `command`, returning its exit code, wall time, peak memory and combined output.

    The process handle is opened right after start and kept until the process has exited,
    so the peak counters can still be read afterwards.
    """
    started = time.perf_counter()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, process.pid
    )
    try:
        output, _ = process.communicate()
        seconds = time.perf_counter() - started
        peak_memory = read_peak_memory(kernel32, handle) if handle else None
    finally:
        if handle:
            kernel32.CloseHandle(handle)
    return Measurement(process.returncode, seconds, peak_memory, output)


def describe_machine(kernel32):
    memory = total_physical_memory(kernel32)
    memory_text = "unknown RAM" if memory is None else f"{memory / 1024**3:.1f} GB RAM"
    return (
        f"{platform.platform()} | {platform.processor()} | {os.cpu_count()} logical CPUs | "
        f"{memory_text} | Python {platform.python_version()}"
    )


def format_megabytes(size):
    return f"{size / BYTES_PER_MB:.1f} MB"


def format_entry(timestamp, command, machine, measurement):
    peak = measurement.peak_memory
    peak_lines = (
        ["peak working set: unavailable", "peak pagefile usage: unavailable"]
        if peak is None
        else [
            f"peak working set (main process only): {format_megabytes(peak.working_set)}",
            f"peak pagefile usage (main process only): {format_megabytes(peak.pagefile)}",
        ]
    )
    output_lines = [f"  {line}" for line in measurement.output.strip().splitlines()]
    return "\n".join(
        [
            f"=== {timestamp} ===",
            f"command: {subprocess.list2cmdline(command)}",
            f"machine: {machine}",
            f"exit code: {measurement.return_code}",
            f"wall time: {measurement.seconds:.2f} s",
            *peak_lines,
            "aggregator output:",
            *output_lines,
            "",
            "",
        ]
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", required=True, help="CSV or zip passed to aggregator.py")
    parser.add_argument(
        "--output",
        help="output directory passed to aggregator.py (default: a temporary directory)",
    )
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="log file to append to")
    return parser.parse_known_args(argv)


def main(argv=None):
    if os.name != "nt":
        print("error: benchmark.py supports Windows only", file=sys.stderr)
        return 2
    args, extra = parse_args(argv)
    kernel32 = load_kernel32()
    with tempfile.TemporaryDirectory() as temporary_output:
        command = [
            sys.executable,
            str(AGGREGATOR),
            "--input",
            args.input,
            "--output",
            args.output or temporary_output,
            *extra,
        ]
        measurement = measure(kernel32, command)
    timestamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    entry = format_entry(timestamp, command, describe_machine(kernel32), measurement)
    with open(args.log, "a", encoding="utf-8") as log:
        log.write(entry)
    print(entry, end="")
    return measurement.return_code


if __name__ == "__main__":
    sys.exit(main())
