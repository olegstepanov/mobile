"""mbl.perf — lightweight runtime profiling helpers."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import time
from typing import Iterator, TextIO


@dataclass
class _PerfState:
    enabled: bool = False
    times: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            self.times[name] += time.perf_counter() - start

    def count(self, name: str, value: int = 1) -> None:
        if self.enabled:
            self.counts[name] += value

    def report(self) -> str:
        lines = ["[mbl profile]"]
        if self.times:
            lines.append("timings:")
            for name, seconds in sorted(self.times.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {name}: {seconds:.3f}s")
        if self.counts:
            lines.append("counts:")
            for name, count in sorted(self.counts.items()):
                lines.append(f"  {name}: {count}")
        if len(lines) == 1:
            lines.append("  (no data)")
        return "\n".join(lines)


_STATE = _PerfState(enabled=os.getenv("MBL_PROFILE", "0").strip() in {"1", "true", "yes"})


@contextmanager
def span(name: str) -> Iterator[None]:
    with _STATE.span(name):
        yield


def count(name: str, value: int = 1) -> None:
    _STATE.count(name, value)


def set_enabled(enabled: bool) -> None:
    _STATE.enabled = enabled
    _STATE.times.clear()
    _STATE.counts.clear()


def is_enabled() -> bool:
    return _STATE.enabled


def emit_report(stream: TextIO) -> None:
    if not _STATE.enabled:
        return
    stream.write(_STATE.report())
    stream.write("\n")

