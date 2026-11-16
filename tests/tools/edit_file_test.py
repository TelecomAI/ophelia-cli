import asyncio
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "tools" / "edit_file.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("edit_file_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edit_file_module = _load_module()
edit_file = edit_file_module.edit_file


def _run(file_path, old, new):
    return asyncio.run(edit_file(str(file_path), old, new))


def test_replaces_unique_string(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")

    _run(f, "world", "OPHELIA")

    assert f.read_text(encoding="utf-8") == "hello OPHELIA"


def test_returns_success_message(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("abc", encoding="utf-8")

    result = _run(f, "abc", "xyz")

    assert "succesfully" in result


def test_shorter_replacement_leaves_no_trailing_garbage(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("long original content", encoding="utf-8")

    _run(f, "long original content", "x")

    assert f.read_text(encoding="utf-8") == "x"


def test_longer_replacement_grows_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")

    _run(f, "a", "a" * 1000)

    assert f.read_text(encoding="utf-8") == "a" * 1000


def test_empty_new_string_deletes_text(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("remove ME now", encoding="utf-8")

    _run(f, " ME", "")

    assert f.read_text(encoding="utf-8") == "remove now"


def test_multiline_replacement(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")

    _run(f, "line2\nline3", "replaced")

    assert f.read_text(encoding="utf-8") == "line1\nreplaced\n"


def test_regex_characters_are_literal(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("price: $5.00 (approx.)", encoding="utf-8")

    _run(f, "$5.00 (approx.)", "[free]")

    assert f.read_text(encoding="utf-8") == "price: [free]"


def test_unicode_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Bonjour é 🚀", encoding="utf-8")

    _run(f, "é 🚀", "à 🎉")

    assert f.read_text(encoding="utf-8") == "Bonjour à 🎉"


def test_new_string_containing_old_string_is_not_reprocessed(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("foo", encoding="utf-8")

    _run(f, "foo", "foofoo")

    assert f.read_text(encoding="utf-8") == "foofoo"


def test_old_string_not_found_raises(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="not found"):
        _run(f, "missing", "x")

    assert f.read_text(encoding="utf-8") == "hello"


def test_old_string_not_unique_raises_and_leaves_file_intact(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("ab ab", encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        _run(f, "ab", "x")

    assert f.read_text(encoding="utf-8") == "ab ab"


def test_overlapping_occurrences_are_counted_as_multiple(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("aaa", encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        _run(f, "aa", "b")

    assert f.read_text(encoding="utf-8") == "aaa"


def test_empty_old_string_raises(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        _run(f, "", "x")

    assert f.read_text(encoding="utf-8") == "hello"


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _run(tmp_path / "nope.txt", "a", "b")


@pytest.mark.parametrize("bad_path", [None, 123, Path("x")])
def test_non_string_file_path_raises(bad_path):
    with pytest.raises(TypeError, match="file_path"):
        asyncio.run(edit_file(bad_path, "a", "b"))


@pytest.mark.parametrize("bad_old", [None, 1, b"a"])
def test_non_string_old_string_raises(tmp_path, bad_old):
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")

    with pytest.raises(TypeError, match="old_string"):
        _run(f, bad_old, "b")


@pytest.mark.parametrize("bad_new", [None, 1, b"b"])
def test_non_string_new_string_raises(tmp_path, bad_new):
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")

    with pytest.raises(TypeError, match="new_string"):
        _run(f, "a", bad_new)


def test_type_error_does_not_modify_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")

    with pytest.raises(TypeError):
        _run(f, "a", None)

    assert f.read_text(encoding="utf-8") == "a"


def test_preserves_crlf(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"a\r\nb\r\nc\r\n")
    _run(f, "b", "X")
    assert f.read_bytes() == b"a\r\nX\r\nc\r\n"
