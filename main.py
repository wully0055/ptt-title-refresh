"""定時爬取 PTT 看板，標題符合關鍵字時寄 Email 通知。"""

import html as html_lib
import json
import logging
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

PTT_BASE_URL = "https://www.ptt.cc"
DEFAULT_CHECK_INTERVAL_SECONDS = 900  # 15 分鐘
DEFAULT_SEEN_POSTS_FILE = "seen_posts.json"

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """設定缺漏或格式錯誤。"""


@dataclass(frozen=True)
class Config:
    ptt_url: str
    keyword: str
    sender_email: str
    receiver_emails: list[str]
    gmail_app_password: str
    check_interval_seconds: int
    seen_posts_file: Path

    REQUIRED_KEYS = (
        "PTT_URL",
        "KEYWORD",
        "SENDER_EMAIL",
        "RECEIVER_EMAILS",
        "GMAIL_APP_PASSWORD",
    )

    @classmethod
    def from_env(cls, env: dict) -> "Config":
        missing = [key for key in cls.REQUIRED_KEYS if not env.get(key, "").strip()]
        if missing:
            raise ConfigError(
                f"缺少必要環境變數：{', '.join(missing)}（請參考 .env.example）"
            )

        receiver_emails = [
            email.strip()
            for email in env["RECEIVER_EMAILS"].split(",")
            if email.strip()
        ]

        return cls(
            ptt_url=env["PTT_URL"].strip(),
            keyword=env["KEYWORD"].strip(),
            sender_email=env["SENDER_EMAIL"].strip(),
            receiver_emails=receiver_emails,
            gmail_app_password=env["GMAIL_APP_PASSWORD"].strip(),
            check_interval_seconds=int(
                env.get("CHECK_INTERVAL_SECONDS", DEFAULT_CHECK_INTERVAL_SECONDS)
            ),
            seen_posts_file=Path(
                env.get("SEEN_POSTS_FILE", DEFAULT_SEEN_POSTS_FILE)
            ),
        )


class SeenStore:
    """已通知文章的持久化紀錄，以文章 URL 去重。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._seen: set[str] = set()
        if self.path.exists():
            self._seen = set(json.loads(self.path.read_text(encoding="utf-8")))

    def is_seen(self, url: str) -> bool:
        return url in self._seen

    def add(self, url: str) -> None:
        self._seen.add(url)

    def save(self) -> None:
        payload = sorted(self._seen)
        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # 寫入失敗時完整留下當下要寫的內容，事後才能依 log 補回
            logger.error(
                "無法寫入 seen posts 檔案 path=%s，當下要寫入的完整內容=%s",
                self.path,
                payload,
                exc_info=True,
            )


def parse_posts(html: str, keyword: str) -> list[tuple[str, str]]:
    """解析看板頁面，回傳標題含關鍵字的 (標題, 完整連結) 清單。

    已刪除的文章（標題沒有連結）會被略過。
    """
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for title_div in soup.find_all("div", class_="title"):
        link = title_div.select_one("a")
        if link is None:  # 已刪除的文章
            continue
        title = title_div.text.strip()
        if keyword.lower() in title.lower():
            posts.append((title, f"{PTT_BASE_URL}{link.get('href')}"))
    return posts


def fetch_page(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException:
        logger.error("抓取頁面失敗 url=%s", url, exc_info=True)
        return None


def board_from_url(url: str) -> str:
    """從文章 URL 取出看板名稱，取不到時回傳空字串。"""
    match = re.search(r"/bbs/([^/]+)/", url)
    return match.group(1) if match else ""


def render_email(
    keyword: str, posts: list[tuple[str, str]], checked_at: str
) -> tuple[str, str, str]:
    """產生通知信的 (主旨, 純文字內文, HTML 內文)。"""
    subject = f"搜尋到 {len(posts)} 篇【{keyword}】相關標題文章"

    text = "\n\n".join(
        f"【{keyword}】關鍵字新文章：{title}\n連結：{url}" for title, url in posts
    )

    cards = []
    for title, url in posts:
        board = board_from_url(url)
        board_line = (
            f'<p style="margin:6px 0 0;font-size:12px;color:#8a8a85;">'
            f"{html_lib.escape(board)}</p>"
            if board
            else ""
        )
        cards.append(
            f'<div style="border:1px solid #e3e1d9;border-radius:8px;'
            f'padding:12px 14px;margin-bottom:10px;">'
            f'<a href="{html_lib.escape(url, quote=True)}" '
            f'style="font-size:15px;color:#185FA5;text-decoration:none;">'
            f"{html_lib.escape(title)}</a>"
            f"{board_line}"
            f"</div>"
        )

    html = (
        '<div style="background:#f5f4ee;padding:24px;">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;'
        "border-radius:8px;border:1px solid #e3e1d9;padding:20px;"
        'font-family:-apple-system,\'Segoe UI\',\'Microsoft JhengHei\',sans-serif;">'
        '<p style="margin:0 0 4px;font-size:13px;color:#8a8a85;">PTT 關鍵字通知</p>'
        f'<p style="margin:0 0 16px;font-size:17px;font-weight:500;color:#2c2c2a;">'
        f"「{html_lib.escape(keyword)}」有 {len(posts)} 篇新文章</p>"
        f"{''.join(cards)}"
        f'<p style="margin:16px 0 0;font-size:11px;color:#b4b2a9;">'
        f"ptt-title-refresh・{html_lib.escape(checked_at)}</p>"
        "</div></div>"
    )

    return subject, text, html


def send_email(config: Config, subject: str, text_body: str, html_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["subject"] = subject
    message["from"] = config.sender_email
    message["to"] = ", ".join(config.receiver_emails)
    # 純文字放前面、HTML 放後面：支援 HTML 的信箱會優先顯示後者
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host="smtp.gmail.com", port=587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config.sender_email, config.gmail_app_password)
            smtp.send_message(message)
        logger.info("通知信已寄出 receivers=%s subject=%s", config.receiver_emails, subject)
    except smtplib.SMTPException:
        logger.error(
            "寄信失敗 receivers=%s subject=%s body=%s",
            config.receiver_emails,
            subject,
            text_body,
            exc_info=True,
        )


def check_once(config: Config, session: requests.Session, store: SeenStore) -> None:
    html = fetch_page(session, config.ptt_url)
    if html is None:
        return

    new_posts = [
        (title, url)
        for title, url in parse_posts(html, config.keyword)
        if not store.is_seen(url)
    ]
    if not new_posts:
        logger.info("本輪沒有新文章 keyword=%s", config.keyword)
        return

    checked_at = time.strftime("%Y-%m-%d %H:%M")
    subject, text_body, html_body = render_email(config.keyword, new_posts, checked_at)
    logger.info("發現 %d 篇新文章：\n%s", len(new_posts), text_body)
    send_email(config, subject, text_body, html_body)

    for _, url in new_posts:
        store.add(url)
    store.save()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv()
    try:
        config = Config.from_env(dict(os.environ))
    except ConfigError as e:
        logger.error("%s", e)
        sys.exit(1)

    store = SeenStore(config.seen_posts_file)
    session = requests.Session()
    session.cookies.set("over18", "1", domain=".ptt.cc")  # 18 禁看板的年齡確認

    logger.info(
        "開始監控 url=%s keyword=%s interval=%ds",
        config.ptt_url,
        config.keyword,
        config.check_interval_seconds,
    )
    while True:
        check_once(config, session, store)
        time.sleep(config.check_interval_seconds)


if __name__ == "__main__":
    main()
