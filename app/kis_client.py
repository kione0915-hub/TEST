"""한국투자증권 OpenAPI REST 클라이언트.

- 접근토큰 발급/캐시 (토큰은 24시간 유효, 재발급 호출이 제한되므로 파일 캐시 사용)
- 현재가/일봉 시세 조회
- 현금 매수/매도 주문 (모의투자는 VT~, 실전은 TT~ TR ID 자동 선택)
- 잔고 조회
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from app.config import Settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = Path(".token_cache.json")  # .gitignore 등록됨
RATE_LIMIT_CODE = "EGW00201"  # 초당 거래건수 초과


class KisApiError(RuntimeError):
    pass


class KisClient:
    # 유량 제한 상태는 클래스 전체가 공유한다.
    # (설정 저장 등으로 클라이언트가 여러 개 생겨도 합산 호출 속도가 한도를 넘지 않도록)
    _throttle_lock = threading.Lock()
    _last_call = 0.0

    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_expire_at: float = 0.0
        self._session = requests.Session()
        # 호출 유량 제한: 모의투자는 초당 2건이라 여유 있게 0.6초 간격을 지킨다
        self._min_interval = 0.6 if settings.is_paper else 0.1

    def _throttle(self) -> None:
        """API 호출 간 최소 간격을 보장한다 (스레드/인스턴스가 여럿이어도 안전)."""
        with KisClient._throttle_lock:
            wait = self._min_interval - (time.monotonic() - KisClient._last_call)
            if wait > 0:
                time.sleep(wait)
            KisClient._last_call = time.monotonic()

    # ---------- 인증 ----------

    def _load_cached_token(self) -> bool:
        try:
            cache = json.loads(TOKEN_CACHE_FILE.read_text())
        except (OSError, ValueError):
            return False
        if cache.get("mode") != self.s.mode:
            return False
        if cache.get("expire_at", 0) - time.time() < 600:  # 만료 10분 전이면 재발급
            return False
        self._token = cache["token"]
        self._token_expire_at = cache["expire_at"]
        return True

    def _issue_token(self) -> None:
        try:
            resp = self._session.post(
                f"{self.s.base_url}/oauth2/tokenP",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.s.app_key,
                    "appsecret": self.s.app_secret,
                },
                timeout=10,
            )
        except requests.RequestException as e:
            raise KisApiError(f"토큰 발급 중 네트워크 오류: {e.__class__.__name__}") from e
        data = resp.json()
        if resp.status_code != 200 or "access_token" not in data:
            raise KisApiError(f"토큰 발급 실패: {data}")
        self._token = data["access_token"]
        self._token_expire_at = time.time() + int(data.get("expires_in", 86400))
        TOKEN_CACHE_FILE.write_text(
            json.dumps({
                "mode": self.s.mode,
                "token": self._token,
                "expire_at": self._token_expire_at,
            })
        )
        logger.info("접근토큰 발급 완료 (mode=%s)", self.s.mode)

    def _ensure_token(self) -> str:
        if self._token and self._token_expire_at - time.time() > 600:
            return self._token
        if self._load_cached_token():
            return self._token
        self._issue_token()
        return self._token

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self.s.app_key,
            "appsecret": self.s.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _hashkey(self, body: dict) -> str:
        self._throttle()
        try:
            resp = self._session.post(
                f"{self.s.base_url}/uapi/hashkey",
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "appkey": self.s.app_key,
                    "appsecret": self.s.app_secret,
                },
                json=body,
                timeout=10,
            )
        except requests.RequestException as e:
            raise KisApiError(f"hashkey 발급 중 네트워크 오류: {e.__class__.__name__}") from e
        data = resp.json()
        if "HASH" not in data:
            raise KisApiError(f"hashkey 발급 실패: {data}")
        return data["HASH"]

    # ---------- 공통 요청 ----------

    def _request(self, method: str, path: str, headers: dict, **kwargs) -> dict:
        """유량 제한을 지키며 요청한다.

        - 한도 초과(EGW00201)면 잠시 대기 후 자동 재시도
        - 일시적 네트워크 오류(서버가 연결을 끊음 등)는 조회(GET)에 한해 자동 재시도.
          주문(POST)은 이중 주문 위험이 있어 재시도하지 않고 오류로 알린다.
        """
        data = {}
        for attempt in range(4):
            self._throttle()
            try:
                resp = self._session.request(
                    method, f"{self.s.base_url}{path}", headers=headers, timeout=10, **kwargs
                )
            except requests.RequestException as e:
                if method == "GET" and attempt < 3:
                    wait = 0.5 * (attempt + 1)
                    logger.warning("일시적 네트워크 오류(%s), %.1f초 후 재시도... (%d/3)",
                                   e.__class__.__name__, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                raise KisApiError(
                    f"네트워크 오류 [{path}]: {e.__class__.__name__} — "
                    "인터넷 연결을 확인하세요. 주문 요청이었다면 계좌에서 체결 여부를 확인하세요."
                ) from e
            try:
                data = resp.json()
            except ValueError:
                if method == "GET" and attempt < 3:
                    logger.warning("서버 응답 해석 실패, 재시도... (%d/3)", attempt + 1)
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise KisApiError(f"서버 응답 해석 실패 [{path}] (HTTP {resp.status_code})")
            if resp.status_code == 200 and data.get("rt_cd") == "0":
                return data
            if data.get("msg_cd") == RATE_LIMIT_CODE:
                wait = 1.0 + attempt
                logger.warning("호출 한도 초과(%s), %.0f초 후 재시도... (%d/3)",
                               RATE_LIMIT_CODE, wait, attempt + 1)
                time.sleep(wait)
                continue
            break
        raise KisApiError(f"API 오류 [{path}]: {data.get('msg_cd')} {data.get('msg1')}")

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        return self._request("GET", path, self._headers(tr_id), params=params)

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        headers = self._headers(tr_id)
        headers["hashkey"] = self._hashkey(body)
        return self._request("POST", path, headers, json=body)

    # ---------- 시세 ----------

    def get_current_price(self, symbol: str) -> int:
        """국내주식 현재가 (원)."""
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        return int(data["output"]["stck_prpr"])

    def get_daily_candles(self, symbol: str) -> list[dict]:
        """최근 일봉 목록 [{date: 'YYYYMMDD', close: int}] (과거 -> 최신 순, 최대 100개).

        MACD 계산에 40개 이상이 필요해 기간별 시세 API를 사용한다.
        """
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",  # 수정주가 반영
            },
        )
        candles = [
            {"date": row["stck_bsop_date"], "close": int(row["stck_clpr"])}
            for row in data["output2"] if row.get("stck_clpr")
        ]
        candles.reverse()  # API는 최신순으로 주므로 과거순으로 뒤집는다
        return candles

    def get_daily_closes(self, symbol: str) -> list[int]:
        """최근 일봉 종가 목록 (과거 -> 최신 순, 최대 100개)."""
        return [c["close"] for c in self.get_daily_candles(symbol)]

    def get_ohlc_candles(self, symbol: str, period: str = "D") -> list[dict]:
        """일(D)/주(W)/월(M)봉 OHLCV 목록 (과거 -> 최신 순, 최대 100개).

        [{date: 'YYYYMMDD', open, high, low, close, volume}]
        """
        days = {"D": 200, "W": 900, "M": 3700}.get(period, 200)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": period,
                "FID_ORG_ADJ_PRC": "0",  # 수정주가 반영
            },
        )
        candles = [
            {
                "date": row["stck_bsop_date"],
                "open": int(row["stck_oprc"]),
                "high": int(row["stck_hgpr"]),
                "low": int(row["stck_lwpr"]),
                "close": int(row["stck_clpr"]),
                "volume": int(row.get("acml_vol") or 0),
            }
            for row in data["output2"] if row.get("stck_clpr")
        ]
        candles.reverse()
        return candles

    def get_minute_candles(self, symbol: str, max_rows: int = 400) -> list[dict]:
        """당일 1분봉 목록 (과거 -> 최신 순).

        API가 1회에 30건(최신부터)만 주므로 시각을 되짚어가며 여러 번 조회한다.
        [{date, time: 'HHMMSS', open, high, low, close, volume}]
        """
        rows: dict[str, dict] = {}  # time -> candle (중복 제거)
        hour = datetime.now().strftime("%H%M%S")
        if hour > "153000":
            hour = "153000"
        for _ in range(max_rows // 30 + 2):
            data = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                tr_id="FHKST03010200",
                params={
                    "FID_ETC_CLS_CODE": "",
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": symbol,
                    "FID_INPUT_HOUR_1": hour,
                    "FID_PW_DATA_INCU_YN": "Y",
                },
            )
            batch = data.get("output2", [])
            new = 0
            earliest = hour
            for row in batch:
                t = row.get("stck_cntg_hour")
                if not t or not row.get("stck_prpr"):
                    continue
                if t not in rows:
                    new += 1
                rows[t] = {
                    "date": row.get("stck_bsop_date", ""),
                    "time": t,
                    "open": int(row["stck_oprc"]),
                    "high": int(row["stck_hgpr"]),
                    "low": int(row["stck_lwpr"]),
                    "close": int(row["stck_prpr"]),
                    "volume": int(row.get("cntg_vol") or 0),
                }
                earliest = min(earliest, t)
            if not batch or new == 0 or len(rows) >= max_rows or earliest <= "090000":
                break
            # 다음 조회는 지금까지 받은 것 중 가장 이른 시각의 1분 전부터
            t = datetime.strptime(earliest, "%H%M%S") - timedelta(minutes=1)
            hour = t.strftime("%H%M%S")
        return [rows[t] for t in sorted(rows)]

    # ---------- 주문 ----------

    def _order(self, symbol: str, qty: int, side: str, price: int = 0) -> dict:
        """현금 주문. side: 'buy' | 'sell'. price=0 이면 시장가."""
        if side == "buy":
            tr_id = "VTTC0802U" if self.s.is_paper else "TTTC0802U"
        else:
            tr_id = "VTTC0801U" if self.s.is_paper else "TTTC0801U"
        body = {
            "CANO": self.s.account_no,
            "ACNT_PRDT_CD": self.s.account_product_cd,
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",  # 01: 시장가, 00: 지정가
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        data = self._post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)
        logger.info("[주문 성공] %s %s x%d (주문번호: %s)",
                    side.upper(), symbol, qty, data["output"].get("ODNO"))
        return data["output"]

    def buy(self, symbol: str, qty: int, price: int = 0) -> dict:
        return self._order(symbol, qty, "buy", price)

    def sell(self, symbol: str, qty: int, price: int = 0) -> dict:
        return self._order(symbol, qty, "sell", price)

    # ---------- 잔고 ----------

    def get_balance(self) -> dict:
        """잔고 조회. 보유종목 목록과 요약(예수금/평가금액)을 돌려준다."""
        tr_id = "VTTC8434R" if self.s.is_paper else "TTTC8434R"
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id=tr_id,
            params={
                "CANO": self.s.account_no,
                "ACNT_PRDT_CD": self.s.account_product_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        holdings = {
            row["pdno"]: {
                "qty": int(row["hldg_qty"]),
                "avg_price": float(row.get("pchs_avg_pric") or 0),  # 매입평균가
            }
            for row in data.get("output1", [])
            if int(row.get("hldg_qty", 0)) > 0
        }
        summary = data.get("output2", [{}])[0]
        return {"holdings": holdings, "summary": summary}
