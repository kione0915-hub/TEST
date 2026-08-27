#!/bin/bash
# Mac 용 실행 파일: 더블클릭하면 대시보드가 열립니다.
cd "$(dirname "$0")"
echo "============================================"
echo " 자동매매 대시보드를 준비하는 중입니다..."
echo "============================================"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[오류] Python 이 설치되어 있지 않습니다."
    echo "https://python.org/downloads 에서 설치하세요."
    read -p "엔터를 누르면 닫힙니다..."
    exit 1
fi

python3 -m pip install -r requirements.txt --quiet
python3 webapp.py
