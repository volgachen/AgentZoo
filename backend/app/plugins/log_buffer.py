from collections import deque
from datetime import datetime, timezone
from typing import Deque, Iterable, Literal
from pydantic import BaseModel


LogStream = Literal["stdout", "stderr", "system"]


class LogLine(BaseModel):
    ts: datetime
    stream: LogStream
    line: str


class LogBuffer:
    """In-memory ring buffer: keep at most `max_lines` lines AND `max_bytes` total."""

    def __init__(self, max_lines: int = 5000, max_bytes: int = 1_000_000) -> None:
        self._lines: Deque[LogLine] = deque()
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._bytes = 0

    def append(self, stream: LogStream, line: str) -> LogLine:
        entry = LogLine(ts=datetime.now(timezone.utc), stream=stream, line=line)
        size = len(line.encode("utf-8", errors="replace"))
        self._lines.append(entry)
        self._bytes += size
        while self._lines and (
            len(self._lines) > self._max_lines or self._bytes > self._max_bytes
        ):
            dropped = self._lines.popleft()
            self._bytes -= len(dropped.line.encode("utf-8", errors="replace"))
        return entry

    def snapshot(self) -> list[LogLine]:
        return list(self._lines)

    def clear(self) -> None:
        self._lines.clear()
        self._bytes = 0

    def extend(self, entries: Iterable[LogLine]) -> None:
        for e in entries:
            self.append(e.stream, e.line)
