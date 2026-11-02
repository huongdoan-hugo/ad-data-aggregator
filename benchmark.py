"""Measure aggregator.py: wall-clock time and peak memory, each run in a fresh process.

Not part of the product. Windows only: peak memory is the child's peak working set,
read through the Win32 API after the child exits. Results are appended to a log file.

Usage: python benchmark.py [--runs 3] [--log benchmark.log] -- --input data\\ad_data.csv --output results
"""
import argparse
import ctypes
import os
import platform
import statistics
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

AGGREGATOR = Path(__file__).with_name("aggregator.py")
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


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


def load_win32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
    ]
    return kernel32, psapi


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark aggregator.py in separate processes.")
    parser.add_argument("--runs", type=positive_int, default=3, help="Number of runs (default: 3)")
    parser.add_argument("--log", type=Path, default=Path("benchmark.log"), help="Log file to append to")
    parser.add_argument("aggregator_args", nargs=argparse.REMAINDER,
                        help="Arguments for aggregator.py, after --")
    args = parser.parse_args()
    if args.aggregator_args[:1] == ["--"]:
        args.aggregator_args = args.aggregator_args[1:]
    if not args.aggregator_args:
        parser.error("pass the aggregator arguments after --, e.g. -- --input data.csv --output results")
    return args


def run_once(command, kernel32, psapi):
    """Run command in a fresh process; return (exit_code, elapsed_s, peak_mib, stdout, stderr)."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, errors="replace")
    # Popen keeps its own handle open until the exit code is read, so this cannot miss the child.
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process.pid)
    if not handle:
        process.kill()
        process.communicate()
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        stdout, stderr = process.communicate()
        elapsed = time.perf_counter() - started
        counters = ProcessMemoryCounters(cb=ctypes.sizeof(ProcessMemoryCounters))
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
    return process.returncode, elapsed, counters.PeakWorkingSetSize / 2**20, stdout, stderr


def main():
    if sys.platform != "win32":
        sys.exit("benchmark.py measures peak memory through the Win32 API and only runs on Windows.")
    args = parse_args()
    kernel32, psapi = load_win32()
    command = [sys.executable, str(AGGREGATOR), *args.aggregator_args]

    with args.log.open("a", encoding="utf-8") as log_file:
        def report(line):
            print(line)
            log_file.write(line + "\n")
            log_file.flush()

        report(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} | Python {platform.python_version()} | "
               f"{platform.platform()} | {os.cpu_count()} CPUs")
        report(f"    command: aggregator.py {subprocess.list2cmdline(args.aggregator_args)}")

        elapsed_runs = []
        peak_runs = []
        for run in range(1, args.runs + 1):
            exit_code, elapsed, peak_mib, stdout, stderr = run_once(command, kernel32, psapi)
            summary = " ".join(stdout.split())
            report(f"run {run}/{args.runs}: {elapsed:.2f}s, peak {peak_mib:.1f} MiB, exit {exit_code} | {summary}")
            if exit_code != 0:
                report(f"    stderr: {' '.join(stderr.split())}")
                return 1
            elapsed_runs.append(elapsed)
            peak_runs.append(peak_mib)

        report(f"summary: elapsed min {min(elapsed_runs):.2f}s / median {statistics.median(elapsed_runs):.2f}s"
               f" / max {max(elapsed_runs):.2f}s, peak memory max {max(peak_runs):.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
