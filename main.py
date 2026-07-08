"""定時爬取 PTT 看板，依監控清單（watches.json）比對關鍵字並寄 Email 通知。"""

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
DEFAULT_WATCHES_FILE = "watches.json"
WATCH_MODES = ("any", "all")

# 模擬瀏覽器，避免被伺服器以預設 python-requests UA 擋掉或重設連線
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
FETCH_MAX_ATTEMPTS = 3
FETCH_RETRY_BASE_DELAY_SECONDS = 2  # 退避基準：第 n 次重試等待 base * 2^(n-1) 秒

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """設定缺漏或格式錯誤。"""


@dataclass(frozen=True)
class Config:
    sender_email: str
    receiver_emails: list[str]
    gmail_app_password: str
    check_interval_seconds: int
    seen_posts_file: Path
    watches_file: Path

    REQUIRED_KEYS = (
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
            sender_email=env["SENDER_EMAIL"].strip(),
            receiver_emails=receiver_emails,
            gmail_app_password=env["GMAIL_APP_PASSWORD"].strip(),
            check_interval_seconds=int(
                env.get("CHECK_INTERVAL_SECONDS", DEFAULT_CHECK_INTERVAL_SECONDS)
            ),
            seen_posts_file=Path(
                env.get("SEEN_POSTS_FILE", DEFAULT_SEEN_POSTS_FILE)
            ),
            watches_file=Path(env.get("WATCHES_FILE", DEFAULT_WATCHES_FILE)),
        )


@dataclass(frozen=True)
class Watch:
    """一個監控項目：在哪個頁面、比對哪些關鍵字。"""

    url: str
    keywords: list[str]
    mode: str = "any"  # any = 任一關鍵字命中；all = 全部關鍵字都要出現
    name: str = ""


def load_watches(path: Path) -> list["Watch"]:
    """讀取並驗證監控清單，格式錯誤時拋出 ConfigError。"""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"找不到監控清單 {path}（請參考 watches.example.json 建立）"
        )

    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} 不是合法的 JSON：{e}") from e

    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path} 必須是至少一個監控項目的清單")

    watches = []
    for index, entry in enumerate(entries, start=1):
        url = str(entry.get("url", "")).strip()
        if not url:
            raise ConfigError(f"{path} 第 {index} 個項目缺少 url")

        keywords = [
            str(keyword).strip()
            for keyword in entry.get("keywords", [])
            if str(keyword).strip()
        ]
        if not keywords:
            raise ConfigError(f"{path} 第 {index} 個項目缺少 keywords")

        mode = entry.get("mode", "any")
        if mode not in WATCH_MODES:
            raise ConfigError(
                f"{path} 第 {index} 個項目的 mode 必須是 {WATCH_MODES}，收到 {mode!r}"
            )

        name = str(entry.get("name", "")).strip() or "＋".join(keywords)
        watches.append(Watch(url=url, keywords=keywords, mode=mode, name=name))

    return watches


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


def match_title(title: str, keywords: list[str], mode: str) -> bool:
    """標題是否命中關鍵字（不分大小寫）。any = 任一；all = 全部。"""
    title_lower = title.lower()
    hits = (keyword.lower() in title_lower for keyword in keywords)
    return all(hits) if mode == "all" else any(hits)


def parse_posts(html: str) -> list[tuple[str, str]]:
    """解析看板頁面，回傳所有 (標題, 完整連結)。已刪除的文章（沒有連結）會略過。"""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for title_div in soup.find_all("div", class_="title"):
        link = title_div.select_one("a")
        if link is None:  # 已刪除的文章
            continue
        title = title_div.text.strip()
        posts.append((title, f"{PTT_BASE_URL}{link.get('href')}"))
    return posts


def fetch_page(session: requests.Session, url: str) -> str | None:
    """抓取頁面，遇到暫時性錯誤時以指數退避重試，全部失敗才回傳 None。

    4xx 屬於設定錯誤（例如網址打錯）而非暫時性問題，不重試。
    """
    for attempt in range(1, FETCH_MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and status < 500:
                logger.error("抓取頁面失敗（HTTP %s，不重試）url=%s", status, url)
                return None
            error = e
        except requests.exceptions.RequestException as e:
            error = e

        if attempt < FETCH_MAX_ATTEMPTS:
            delay = FETCH_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "抓取頁面失敗（%s），%d 秒後重試（第 %d/%d 次）url=%s",
                error,
                delay,
                attempt,
                FETCH_MAX_ATTEMPTS,
                url,
            )
            time.sleep(delay)
        else:
            logger.error(
                "抓取頁面失敗，已重試 %d 次仍失敗 url=%s",
                FETCH_MAX_ATTEMPTS,
                url,
                exc_info=error,
            )
    return None


def board_from_url(url: str) -> str:
    """從文章 URL 取出看板名稱，取不到時回傳空字串。"""
    match = re.search(r"/bbs/([^/]+)/", url)
    return match.group(1) if match else ""


def render_email(
    watch_name: str, posts: list[tuple[str, str]], checked_at: str
) -> tuple[str, str, str]:
    """產生通知信的 (主旨, 純文字內文, HTML 內文)。"""
    subject = f"【{watch_name}】搜尋到 {len(posts)} 篇新文章"

    text = "\n\n".join(
        f"【{watch_name}】新文章：{title}\n連結：{url}" for title, url in posts
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
        f"「{html_lib.escape(watch_name)}」有 {len(posts)} 篇新文章</p>"
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


def run_cycle(
    config: Config,
    watches: list[Watch],
    session: requests.Session,
    store: SeenStore,
) -> None:
    """跑一輪：每個 URL 只抓一次，逐一比對各監控項目並通知。"""
    pages: dict[str, list[tuple[str, str]] | None] = {}
    for url in {watch.url for watch in watches}:
        html = fetch_page(session, url)
        pages[url] = parse_posts(html) if html is not None else None

    notified = False
    for watch in watches:
        posts = pages[watch.url]
        if posts is None:
            continue

        new_posts = [
            (title, url)
            for title, url in posts
            if match_title(title, watch.keywords, watch.mode)
            and not store.is_seen(url)
        ]
        if not new_posts:
            logger.info("「%s」本輪沒有新文章", watch.name)
            continue

        checked_at = time.strftime("%Y-%m-%d %H:%M")
        subject, text_body, html_body = render_email(watch.name, new_posts, checked_at)
        logger.info("發現 %d 篇新文章：\n%s", len(new_posts), text_body)
        send_email(config, subject, text_body, html_body)

        for _, url in new_posts:
            store.add(url)
        notified = True

    if notified:
        store.save()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv()
    try:
        config = Config.from_env(dict(os.environ))
        watches = load_watches(config.watches_file)
    except ConfigError as e:
        logger.error("%s", e)
        sys.exit(1)

    store = SeenStore(config.seen_posts_file)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.cookies.set("over18", "1", domain=".ptt.cc")  # 18 禁看板的年齡確認

    for watch in watches:
        logger.info(
            "監控項目「%s」 url=%s keywords=%s mode=%s",
            watch.name,
            watch.url,
            watch.keywords,
            watch.mode,
        )
    logger.info("每 %d 秒檢查一次", config.check_interval_seconds)

    while True:
        run_cycle(config, watches, session, store)
        time.sleep(config.check_interval_seconds)


if __name__ == "__main__":
    main()
