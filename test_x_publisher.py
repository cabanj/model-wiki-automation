"""Formatting and safety tests for the X publisher (no network)."""

import x_publisher as X


def test_message_within_limit():
    text = X.format_message(["stealth/space-bunny-alpha"], ["inclusionai/ling-3.0-flash-vl"])
    assert len(text) <= X.CHAR_LIMIT
    assert text.startswith("Free Model Roster Update")
    assert "Added: stealth/space-bunny-alpha" in text
    assert "Dropped: inclusionai/ling-3.0-flash-vl" in text
    assert X.SITE_URL in text
    assert X.HASHTAGS in text


def test_long_roster_truncates_with_more_marker():
    added = [f"vendor/very-long-model-identifier-{i:02d}" for i in range(40)]
    removed = [f"vendor/gone-model-{i:02d}" for i in range(10)]
    text = X.format_message(added, removed)
    assert len(text) <= X.CHAR_LIMIT
    assert "more)" in text


def test_empty_ids_are_ignored():
    text = X.format_message(["", "  "], ["a/real-model"])
    assert "Added:" not in text
    assert "Dropped: a/real-model" in text


def test_no_at_url_artifact_in_post():
    # "@url:" is a scraper artifact, not X syntax; a leading @ would also
    # mention an unrelated user.
    text = X.format_message(["a/model"], [])
    assert "@url" not in text
    assert "https://llmroster.dev" in text


def test_latest_change_reads_history(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('[{"at": "t1", "added": ["a/one"], "removed": []},'
                    ' {"at": "t2", "added": [], "removed": ["b/two"]}]', encoding="utf-8")
    entry = X.latest_change(str(path))
    assert entry["removed"] == ["b/two"]
    assert len(X.format_message(entry["added"], entry["removed"])) <= X.CHAR_LIMIT
