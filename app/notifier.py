"""알림 발송 (텔레그램).

텔레그램 봇 토큰/채팅 ID가 설정되어 있으면 휴대폰으로 알림을 보내고,
없으면 화면(로그)에만 표시한다.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, message: str) -> None:
        logger.info("[알림]\n%s", message)
        if not self.telegram_enabled:
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error("텔레그램 발송 실패: %s", resp.text)
        except requests.RequestException as e:
            logger.error("텔레그램 발송 오류: %s", e)
