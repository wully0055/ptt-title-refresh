import json

import pytest

from main import Config, ConfigError, SeenStore, parse_posts

# --- Config ---

REQUIRED_ENV = {
    "PTT_URL": "https://www.ptt.cc/bbs/Drama-Ticket/index.html",
    "KEYWORD": "五月天",
    "SENDER_EMAIL": "me@gmail.com",
    "RECEIVER_EMAILS": "a@gmail.com, b@gmail.com",
    "GMAIL_APP_PASSWORD": "secret",
}


def test_config_from_env_reads_all_fields():
    config = Config.from_env({**REQUIRED_ENV, "CHECK_INTERVAL_SECONDS": "60"})

    assert config.ptt_url == REQUIRED_ENV["PTT_URL"]
    assert config.keyword == "五月天"
    assert config.sender_email == "me@gmail.com"
    assert config.receiver_emails == ["a@gmail.com", "b@gmail.com"]
    assert config.gmail_app_password == "secret"
    assert config.check_interval_seconds == 60


def test_config_missing_required_keys_raises_with_names():
    env = {k: v for k, v in REQUIRED_ENV.items() if k != "GMAIL_APP_PASSWORD"}
    env.pop("KEYWORD")

    with pytest.raises(ConfigError) as exc_info:
        Config.from_env(env)

    assert "KEYWORD" in str(exc_info.value)
    assert "GMAIL_APP_PASSWORD" in str(exc_info.value)


def test_config_blank_value_counts_as_missing():
    with pytest.raises(ConfigError) as exc_info:
        Config.from_env({**REQUIRED_ENV, "KEYWORD": "  "})

    assert "KEYWORD" in str(exc_info.value)


def test_config_check_interval_defaults_to_15_minutes():
    config = Config.from_env(REQUIRED_ENV)

    assert config.check_interval_seconds == 900


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


def test_parse_posts_returns_matching_titles_with_full_links():
    posts = parse_posts(PAGE_HTML, "五月天")

    assert posts == [
        (
            "[徵求] 五月天 5/24 場次兩張",
            "https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html",
        )
    ]


def test_parse_posts_matches_keyword_case_insensitively():
    posts = parse_posts(PAGE_HTML, "mayday")

    assert [title for title, _ in posts] == ["[請益] MAYDAY 演唱會問題"]


def test_parse_posts_skips_deleted_posts_without_crashing():
    posts = parse_posts(PAGE_HTML, "本文已被刪除")

    assert posts == []


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

from main import board_from_url, render_email  # noqa: E402

POSTS = [
    ("[徵求] 五月天 5/24 場次兩張", "https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html"),
    ("[售票] 五月天 6/01 兩張原價", "https://www.ptt.cc/bbs/Drama-Ticket/M.222.A.BBB.html"),
]


def test_board_from_url_extracts_board_name():
    assert board_from_url("https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html") == "Drama-Ticket"


def test_board_from_url_falls_back_to_empty_string():
    assert board_from_url("https://example.com/whatever") == ""


def test_render_email_subject_mentions_count_and_keyword():
    subject, _, _ = render_email("五月天", POSTS, checked_at="2026-07-07 10:15")

    assert subject == "搜尋到 2 篇【五月天】相關標題文章"


def test_render_email_text_fallback_contains_titles_and_links():
    _, text, _ = render_email("五月天", POSTS, checked_at="2026-07-07 10:15")

    for title, url in POSTS:
        assert title in text
        assert url in text


def test_render_email_html_links_titles_and_shows_board():
    _, _, html = render_email("五月天", POSTS, checked_at="2026-07-07 10:15")

    assert '<a href="https://www.ptt.cc/bbs/Drama-Ticket/M.111.A.AAA.html"' in html
    assert "[徵求] 五月天 5/24 場次兩張" in html
    assert "Drama-Ticket" in html
    assert "2026-07-07 10:15" in html


def test_render_email_escapes_html_in_titles():
    posts = [("<b>五月天 & Friends</b>", "https://www.ptt.cc/bbs/x/M.1.html")]

    _, _, html = render_email("五月天", posts, checked_at="2026-07-07 10:15")

    assert "<b>" not in html
    assert "&lt;b&gt;五月天 &amp; Friends&lt;/b&gt;" in html
