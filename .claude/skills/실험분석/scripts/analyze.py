#!/usr/bin/env python3
"""실험 데이터 디렉터리의 CSV·로그 파일을 훑어 기초 통계를 JSON으로 출력한다.

사용법: python analyze.py <data_dir> [--json-out <path>]

CSV마다: 행 수, 컬럼별 결측 수, 중복 행 수, 숫자 컬럼의 평균·표준편차·최소·최대.
로그(.log/.txt)마다: 줄 수, ERROR/WARN 포함 줄 수와 해당 줄 샘플.
숫자 판정은 값의 80% 이상이 float 변환 가능한 컬럼 기준. 결측은 빈 문자열,
NA/N/A/NaN/null/None/- 을 포함한다. 외부 패키지 없이 표준 라이브러리만 쓴다.
"""
import csv
import json
import math
import sys
from pathlib import Path

MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-"}


def is_missing(value: str) -> bool:
    return value.strip().lower() in MISSING_TOKENS


def analyze_csv(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return {"file": str(path), "error": "empty file"}

    header, data = rows[0], rows[1:]
    ncols = len(header)
    data = [row + [""] * (ncols - len(row)) for row in data]

    seen, dup_count = set(), 0
    for row in data:
        key = tuple(row)
        if key in seen:
            dup_count += 1
        seen.add(key)

    columns = {}
    for i, name in enumerate(header):
        values = [row[i] for row in data]
        missing = sum(1 for v in values if is_missing(v))
        present = [v for v in values if not is_missing(v)]
        numeric = []
        for v in present:
            try:
                numeric.append(float(v))
            except ValueError:
                pass
        col = {"missing": missing}
        if present and len(numeric) >= 0.8 * len(present):
            n = len(numeric)
            mean = sum(numeric) / n
            var = sum((x - mean) ** 2 for x in numeric) / (n - 1) if n > 1 else 0.0
            col.update(
                {
                    "count": n,
                    "mean": round(mean, 6),
                    "std": round(math.sqrt(var), 6),
                    "min": min(numeric),
                    "max": max(numeric),
                }
            )
        else:
            col["type"] = "non-numeric"
            col["unique"] = len(set(present))
        columns[name] = col

    return {
        "file": str(path),
        "rows": len(data),
        "duplicate_rows": dup_count,
        "columns": columns,
    }


def analyze_log(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    errors = [l for l in lines if "error" in l.lower()]
    warns = [l for l in lines if "warn" in l.lower()]
    return {
        "file": str(path),
        "lines": len(lines),
        "error_lines": len(errors),
        "warn_lines": len(warns),
        "error_samples": errors[:5],
        "warn_samples": warns[:5],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    data_dir = Path(sys.argv[1])
    if not data_dir.is_dir():
        print(f"디렉터리를 찾을 수 없음: {data_dir}", file=sys.stderr)
        return 1

    result = {
        "data_dir": str(data_dir),
        "condition": data_dir.name,
        "csv": [analyze_csv(p) for p in sorted(data_dir.rglob("*.csv"))],
        "logs": [
            analyze_log(p)
            for ext in ("*.log", "*.txt")
            for p in sorted(data_dir.rglob(ext))
        ],
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if "--json-out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--json-out") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
