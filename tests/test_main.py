import json
import logging

import pytest
import requests

import main as main_mod
from main import (
    Config,
    ConfigError,
    SeenStore,
    Watch,
    board_from_url,
    fetch_page,
    load_watches,
    match_title,
    parse_posts,
    render_email,
    run_cycle,
)

# --- Config ---

REQUIRED_ENV = {
    "SENDER_EMAIL": "me@gmail.com",
    "RECEIVER_EMAILS": "a@gmail.com, b@gmail.com",
    "GMAIL_APP_PASSWORD": "secret",
}


def test_config_from_env_reads_all_fields():
    config = Config.from_env({**REQUIRED_ENV, "CHECK_INTERVAL_SECONDS": "60"})

    assert config.sender_email == "me@gmail.com"
    assert config.receiver_emails == ["a@gmail.com", "b@gmail.com"]
    assert config.gmail_app_password == "secret"
    assert config.check_interval_seconds == 60


def test_config_missing_required_keys_raises_with_names():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "GMAIL_APP_PASSWORD"}
    env.pop("SENDER_EMAIL")

    with pytest.raises(ConfigError) as exc_info:
        Config.from_env(env)

    assert "SENDER_EMAIL" in str(exc_info.value)
    assert "GMAIL_APP_PASSWORD" in str(exc_info.value)


def test_config_blank_value_counts_as_missing():
    with pytest.raises(ConfigError) as exc_info:
        Config.from_env({**REQUIRED_ENV, "SENDER_EMAIL": "  "})

    assert "SENDER_EMAIL" in str(exc_info.value)


def test_config_check_interval_defaults_to_15_minutes():
    config = Config.from_env(REQUIRED_ENV)

    assert config.check_interval_seconds == 900


def test_config_watches_file_defaults_to_watches_json():
    config = Config.from_env(REQUIRED_ENV)

    assert str(config.watches_file) == "watches.json"


# --- Watches ---

VALID_WATCHES = [
    {
        "name": "五月天票券",
        "url": "https://www.ptt.cc/bbs/Drama-Ticket/index.html",
        "keywords": ["五月天", "MAYDAY"],
        "mode": "any",
    },
    {
        "url": "https://www.ptt.cc/bbs/Ticket/index.html",
        "keywords": ["周杰倫"],
    },
]


def write_watches(tmp_path, data):
    path = tmp_path / "watches.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_watches_parses_valid_file(tmp_path):
    watches = load_watches(write_watches(tmp_path, VALID_WATCHES))

    assert watches[0] == Watch(
        name="五月天票券",
        url="https://www.ptt.cc/bbs/Drama-Ticket/index.html",
        keywords=["五月天", "MAYDAY"],
        mode="any",
    )


def test_load_watches_defaults_mode_to_any_and_name_to_keywords(tmp_path):
    watches = load_watches(write_watches(tmp_path, VALID_WATCHES))

    assert watches[1].mode == "any"
    assert watches[1].name == "周杰倫"


def test_load_watches_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError) as exc_info:
        load_watches(tmp_path / "nope.json")

    assert "nope.json" in str(exc_info.value)


def test_load_watches_empty_list_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_watches(write_watches(tmp_path, []))


def test_load_watches_missing_url_raises_with_position(tmp_path):
    data = [{"keywords": ["x"]}]

    with pytest.raises(ConfigError) as exc_info:
        load_watches(write_watches(tmp_path, data))

    assert "url" in str(exc_info.value)
    assert "1" in str(exc_info.value)


def test_load_watches_empty_keywords_raises(tmp_path):
    data = [{"url": "https://www.ptt.cc/bbs/X/index.html", "keywords": []}]

    with pytest.raises(ConfigError):
        load_watches(write_watches(tmp_path, data))


def test_load_watches_invalid_mode_raises(tmp_path):
    data = [
        {
            "url": "https://www.ptt.cc/bbs/X/index.html",
            "keywords": ["x"],
            "mode": "both",
        }
    ]

    with pytest.raises(ConfigError) as exc_info:
        load_watches(write_watches(tmp_path, data))

    assert "mode" in str(exc_info.value)


# --- match_title ---


def test_match_title_any_mode_matches_one_keyword():
    assert match_title("[徵求] 五月天 5/24 兩張", ["五月天", "告五人"], "any")


def test_match_title_any_mode_no_keyword_matches():
    assert not match_title("[售票] 告五人 6/01", ["五月天", "MAYDAY"], "any")


def test_match_title_is_case_insensitive():
    assert match_title("[請益] MAYDAY 演唱會問題", ["mayday"], "any")


def test_match_title_all_mode_requires_every_keyword():
    title = "[徵求] 五月天 5/24 兩張"

    assert match_title(title, ["五月天", "徵求"], "all")
    assert not match_title(title, ["五月天", "售票"], "all")


# --- parse_posts ---

PAGE_HTML = """
<html><body>
<div class="r-ent">
  <div class="title"><a href="/bbs/Drama-Ticket/M.111.A.AAA.html">[徵求] 五月天 5/24 場次兩張</a></div>
</div>
<div class="r-ent">
  <div class="title"><a href="/bbs/Drama-Ticket/M.222.A.BBB.html">[售票] 告五人 6/01</a></div>
</div>
<div class="r-ent">
  <div class="title">(本文已被刪除) [xxx]</div>
</div>
<div class="r-ent">
  <div class="title"><a href="/bbs/Drama-Ticket/M.333.A.CCC.html">[請益] MAYDAY 演唱會問題</a></div>
</div>
</body></html>
"""


def test_parse_posts_returns_all_posts_with_full_links():
    posts = parse_posts(PAGE_HTML)

    assert posts == [
        (
            "[徵求] 五月天 5/24 場次兩張",
            "https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html",
        ),
        (
            "[售票] 告五人 6/01",
            "https://www.ptt.cc/bbs/Drama-Ticket/M.222.A.BBB.html",
        ),
        (
            "[請益] MAYDAY 演唱會問題",
            "https://www.ptt.cc/bbs/Drama-Ticket/M.333.A.CCC.html",
        ),
    ]


def test_parse_posts_skips_deleted_posts_without_crashing():
    posts = parse_posts(PAGE_HTML)

    assert all("本文已被刪除" not in title for title, _ in posts)


# --- SeenStore ---


def test_seen_store_starts_empty_when_file_missing(tmp_path):
    store = SeenStore(tmp_path / "seen.json")

    assert not store.is_seen("https://www.ptt.cc/bbs/x/M.1.html")


def test_seen_store_persists_across_instances(tmp_path):
    path = tmp_path / "seen.json"
    url = "https://www.ptt.cc/bbs/x/M.1.html"

    store = SeenStore(path)
    store.add(url)
    store.save()

    reloaded = SeenStore(path)
    assert reloaded.is_seen(url)


def test_seen_store_writes_valid_json_list(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.add("url-1")
    store.add("url-2")
    store.save()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(saved) == ["url-1", "url-2"]


# --- render_email ---

POSTS = [
    ("[徵求] 五月天 5/24 場次兩張", "https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html"),
    ("[售票] 五月天 6/01 兩張原價", "https://www.ptt.cc/bbs/Drama-Ticket/M.222.A.BBB.html"),
]


def test_board_from_url_extracts_board_name():
    assert board_from_url("https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html") == "Drama-Ticket"


def test_board_from_url_falls_back_to_empty_string():
    assert board_from_url("https://example.com/whatever") == ""


def test_render_email_subject_mentions_watch_name_and_count():
    subject, _, _ = render_email("五月天票券", POSTS, checked_at="2026-07-07 10:15")

    assert subject == "【五月天票券】搜尋到 2 篇新文章"


def test_render_email_text_fallback_contains_titles_and_links():
    _, text, _ = render_email("五月天票券", POSTS, checked_at="2026-07-07 10:15")

    for title, url in POSTS:
        assert title in text
        assert url in text


def test_render_email_html_links_titles_and_shows_board():
    _, _, html = render_email("五月天票券", POSTS, checked_at="2026-07-07 10:15")

    assert '<a href="https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html"' in html
    assert "[徵求] 五月天 5/24 場次兩張" in html
    assert "Drama-Ticket" in html
    assert "2026-07-07 10:15" in html


def test_render_email_escapes_html_in_titles():
    posts = [("<b>五月天 & Friends</b>", "https://www.ptt.cc/bbs/x/M.1.html")]

    _, _, html = render_email("五月天", posts, checked_at="2026-07-07 10:15")

    assert "<b>" not in html
    assert "&lt;b&gt;五月天 &amp; Friends&lt;/b&gt;" in html


# --- run_cycle ---


def test_run_cycle_fetches_each_url_once_and_notifies_per_watch(monkeypatch, tmp_path):
    url = "https://www.ptt.cc/bbs/Drama-Ticket/index.html"
    fetched = []
    monkeypatch.setattr(
        main_mod, "fetch_page", lambda session, u: (fetched.append(u), PAGE_HTML)[1]
    )
    sent = []
    monkeypatch.setattr(
        main_mod,
        "send_email",
        lambda config, subject, text, html: sent.append(subject),
    )

    config = Config.from_env(REQUIRED_ENV)
    watches = [
        Watch(name="五月天", url=url, keywords=["五月天"], mode="any"),
        Watch(name="MAYDAY", url=url, keywords=["mayday"], mode="any"),
    ]
    store = SeenStore(tmp_path / "seen.json")

    run_cycle(config, watches, None, store)

    assert fetched == [url]
    assert sent == ["【五月天】搜尋到 1 篇新文章", "【MAYDAY】搜尋到 1 篇新文章"]


def test_run_cycle_does_not_renotify_seen_posts(monkeypatch, tmp_path):
    url = "https://www.ptt.cc/bbs/Drama-Ticket/index.html"
    monkeypatch.setattr(main_mod, "fetch_page", lambda session, u: PAGE_HTML)
    sent = []
    monkeypatch.setattr(
        main_mod,
        "send_email",
        lambda config, subject, text, html: sent.append(subject),
    )

    config = Config.from_env(REQUIRED_ENV)
    watches = [Watch(name="五月天", url=url, keywords=["五月天"], mode="any")]
    store = SeenStore(tmp_path / "seen.json")

    run_cycle(config, watches, None, store)
    run_cycle(config, watches, None, store)

    assert len(sent) == 1


# --- fetch_page ---


class FakeResponse:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )


class FakeSession:
    """依序回傳 outcomes 裡的結果；Exception 會被 raise。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(main_mod.time, "sleep", recorded.append)
    return recorded


def test_fetch_page_returns_text_on_success(sleeps):
    session = FakeSession([FakeResponse("page content")])

    assert fetch_page(session, "https://www.ptt.cc/bbs/X/index.html") == "page content"
    assert sleeps == []


def test_fetch_page_retries_connection_error_with_backoff(sleeps):
    session = FakeSession(
        [
            requests.exceptions.ConnectionError("Connection reset by peer"),
            FakeResponse("recovered"),
        ]
    )

    assert fetch_page(session, "https://www.ptt.cc/bbs/X/index.html") == "recovered"
    assert session.calls == 2
    assert sleeps == [2]


def test_fetch_page_gives_up_after_max_attempts(sleeps):
    session = FakeSession(
        [requests.exceptions.ConnectionError("reset")] * 3
    )

    assert fetch_page(session, "https://www.ptt.cc/bbs/X/index.html") is None
    assert session.calls == 3
    assert sleeps == [2, 4]


def test_fetch_page_retries_server_errors(sleeps):
    session = FakeSession([FakeResponse(status=503), FakeResponse("recovered")])

    assert fetch_page(session, "https://www.ptt.cc/bbs/X/index.html") == "recovered"
    assert session.calls == 2


def test_fetch_page_does_not_retry_client_http_errors(sleeps):
    session = FakeSession([FakeResponse(status=404), FakeResponse("never reached")])

    assert fetch_page(session, "https://www.ptt.cc/bbs/X/index.html") is None
    assert session.calls == 1
    assert sleeps == []


def test_fetch_page_retry_warning_includes_failure_reason(sleeps, caplog):
    session = FakeSession(
        [
            requests.exceptions.ConnectionError("Connection reset by peer"),
            FakeResponse("recovered"),
        ]
    )

    with caplog.at_level(logging.WARNING):
        fetch_page(session, "https://www.ptt.cc/bbs/X/index.html")

    assert "Connection reset by peer" in caplog.text
