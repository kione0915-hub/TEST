"""한국투자증권 OpenAPI REST 클라이언트.

- 접근토큰 발급/캐시 (토큰은 24시간 유효, 재발급 호출이 제한되므로 파일 캐시 사용)
- 현재가/일봉 시세 조회
- 현금 매수/매도 주문 (모의투자는 VT~, 실전은 TT~ TR ID 자동 선택)
- 잔고 조회
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from app.config import Settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = Path(".token_cache.json")  # .gitignore 등록됨


class KisApiError(RuntimeError):
    pass


class KisClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_expire_at: float = 0.0
        self._session = requests.Session()

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
        resp = self._session.post(
            f"{self.s.base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.s.app_key,
                "appsecret": self.s.app_secret,
            },
            timeout=10,
        )
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
        data = resp.json()
        if "HASH" not in data:
            raise KisApiError(f"hashkey 발급 실패: {data}")
        return data["HASH"]

    # ---------- 공통 요청 ----------

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        resp = self._session.get(
            f"{self.s.base_url}{path}", headers=self._headers(tr_id), params=params, timeout=10
        )
        data = resp.json()
        if resp.status_code != 200 or data.get("rt_cd") != "0":
            raise KisApiError(f"API 오류 [{path}]: {data.get('msg_cd')} {data.get('msg1')}")
        return data

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        headers = self._headers(tr_id)
        headers["hashkey"] = self._hashkey(body)
        resp = self._session.post(
            f"{self.s.base_url}{path}", headers=headers, json=body, timeout=10
        )
        data = resp.json()
        if resp.status_code != 200 or data.get("rt_cd") != "0":
            raise KisApiError(f"API 오류 [{path}]: {data.get('msg_cd')} {data.get('msg1')}")
        return data

    # ---------- 시세 ----------

    def get_current_price(self, symbol: str) -> int:
        """국내주식 현재가 (원)."""
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        return int(data["output"]["stck_prpr"])

    def get_daily_closes(self, symbol: str) -> list[int]:
        """최근 일봉 종가 목록 (과거 -> 최신 순, 최대 100개).

        MACD(12/26/9) 계산에 40개 이상이 필요해 기간별 시세 API를 사용한다.
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
        closes = [int(row["stck_clpr"]) for row in data["output2"] if row.get("stck_clpr")]
        closes.reverse()  # API는 최신순으로 주므로 과거순으로 뒤집는다
        return closes

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
            row["pdno"]: int(row["hldg_qty"])
            for row in data.get("output1", [])
            if int(row.get("hldg_qty", 0)) > 0
        }
        summary = data.get("output2", [{}])[0]
        return {"holdings": holdings, "summary": summary}
