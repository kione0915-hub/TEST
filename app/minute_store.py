"""분봉 로컬 저장소.

모의투자 API는 당일 분봉을 최근 30개까지만 주므로,
앱이 켜져 있는 동안 분봉을 계속 수집해 data/ 폴더에 쌓아둔다 (git 제외).
쌓인 만큼 차트에서 며칠치 분봉을 볼 수 있다.
"""

import json
import threading
from pathlib import Path

KEEP_DAYS = 7  # 최근 N 거래일만 보관


class MinuteStore:
    def __init__(self, base_dir: str | Path = "data"):
        self.dir = Path(base_dir)
        self._lock = threading.Lock()

    def _path(self, code: str) -> Path:
        return self.dir / f"minutes_{code}.json"

    def _load(self, code: str) -> dict:
        try:
            return json.loads(self._path(code).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def merge(self, code: str, rows: list[dict]) -> int:
        """분봉 목록을 저장소에 합친다. 새로 추가된 개수 반환.

        rows: [{date, time, open, high, low, close, volume}]
        """
        if not rows:
            return 0
        with self._lock:
            data = self._load(code)
            added = 0
            for r in rows:
                day = r.get("date") or ""
                t = r.get("time") or ""
                if len(day) != 8 or not t:
                    continue
                bucket = data.setdefault(day, {})
                if t not in bucket:
                    added += 1
                bucket[t] = [r["open"], r["high"], r["low"], r["close"], r["volume"]]
            # 오래된 날짜 정리
            for day in sorted(data)[:-KEEP_DAYS]:
                del data[day]
            if added:
                self.dir.mkdir(parents=True, exist_ok=True)
                self._path(code).write_text(
                    json.dumps(data, separators=(",", ":")), encoding="utf-8")
            return added

    def get(self, code: str) -> list[dict]:
        """저장된 전체 분봉 (과거 -> 최신 순)."""
        with self._lock:
            data = self._load(code)
        out = []
        for day in sorted(data):
            for t in sorted(data[day]):
                o, h, l, c, v = data[day][t]
                out.append({"date": day, "time": t,
                            "open": o, "high": h, "low": l, "close": c, "volume": v})
        return out
