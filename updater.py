"""자동 업데이트: 실행할 때마다 GitHub에서 최신 코드를 받아와 적용한다.

- start.bat / start.command 이 앱 시작 전에 이 스크립트를 먼저 실행한다
- 내 설정 파일(.env, alert_rules.json, .token_cache.json)은 저장소에 없으므로
  덮어써지지 않고 항상 그대로 유지된다
- 인터넷이 안 되거나 GitHub 접속에 실패하면 그냥 현재 버전으로 실행한다
"""

import io
import os
import shutil
import tempfile
import urllib.request
import zipfile

BRANCH = "main"
REPO_ZIP_URL = f"https://codeload.github.com/kione0915-hub/TEST/zip/refs/heads/{BRANCH}"
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _github_token() -> str:
    """.env 의 GITHUB_TOKEN (있으면). 비공개 저장소 업데이트용."""
    env_path = os.path.join(APP_DIR, ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def main() -> None:
    print("[업데이트] 최신 버전 확인 중...")
    headers = {"User-Agent": "kis-auto-trader-updater"}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(REPO_ZIP_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        print(f"[업데이트] 확인 실패(HTTP {e.code}) — 현재 버전으로 실행합니다.")
        if e.code == 404 and not token:
            print("  -> 저장소가 비공개(private)면 프로그램이 접근할 수 없습니다.")
            print("     해결: GitHub 저장소를 Public 으로 바꾸거나,")
            print("     .env 파일에 GITHUB_TOKEN=토큰값 한 줄을 추가하세요.")
        return
    except Exception as e:
        print(f"[업데이트] 확인 실패({e.__class__.__name__}) — 현재 버전으로 실행합니다.")
        return

    try:
        updated = 0
        with zipfile.ZipFile(io.BytesIO(data)) as zf, tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            root = os.path.join(tmp, os.listdir(tmp)[0])  # ZIP 안의 최상위 폴더
            for dirpath, _dirnames, filenames in os.walk(root):
                rel = os.path.relpath(dirpath, root)
                dest_dir = APP_DIR if rel == "." else os.path.join(APP_DIR, rel)
                os.makedirs(dest_dir, exist_ok=True)
                for name in filenames:
                    src = os.path.join(dirpath, name)
                    dst = os.path.join(dest_dir, name)
                    with open(src, "rb") as f:
                        new_bytes = f.read()
                    old_bytes = None
                    if os.path.exists(dst):
                        with open(dst, "rb") as f:
                            old_bytes = f.read()
                    if old_bytes != new_bytes:
                        shutil.copyfile(src, dst)
                        updated += 1
        if updated:
            print(f"[업데이트] 완료! (파일 {updated}개 갱신)")
        else:
            print("[업데이트] 이미 최신 버전입니다.")
    except Exception as e:
        print(f"[업데이트] 적용 실패({e.__class__.__name__}) — 현재 버전으로 실행합니다.")


if __name__ == "__main__":
    main()
