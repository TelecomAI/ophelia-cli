import asyncio

import pytest

from src.tools.read_file import SCHEMA, read_file


def test_read_existing_file(tmp_path):
    """Test 1: Read an existing text file."""
    file_path = tmp_path / "hello.txt"
    file_path.write_text("Hello OPHELIA!", encoding="utf-8")

    result = asyncio.run(read_file(str(file_path)))

    assert result == "Hello OPHELIA!"


def test_read_empty_file(tmp_path):
    """Test 2: Read an empty file."""
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = asyncio.run(read_file(str(file_path)))

    assert result == ""


def test_read_unicode_and_multiline_content(tmp_path):
    """Test 3: Read special characters and multiple lines."""
    file_path = tmp_path / "unicode.txt"
    content = "Ligne 1 : Bonjour !\nLigne 2 : é è à 🚀"
    file_path.write_text(content, encoding="utf-8")

    result = asyncio.run(read_file(str(file_path)))

    assert result == content


def test_read_line_range(tmp_path):
    """Test 4: Read a specific 1-indexed inclusive line range."""
    file_path = tmp_path / "lines.txt"
    file_path.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    result = asyncio.run(read_file(str(file_path), line_start=2, line_end=3))

    assert result == "line 2\nline 3\n"


def test_read_partial_line_bounds(tmp_path):
    """Test 5: Read with only line_start or only line_end specified."""
    file_path = tmp_path / "lines.txt"
    file_path.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

    from_start = asyncio.run(read_file(str(file_path), line_end=2))
    to_end = asyncio.run(read_file(str(file_path), line_start=2))

    assert from_start == "line 1\nline 2\n"
    assert to_end == "line 2\nline 3\n"


def test_read_invalid_line_range(tmp_path):
    """Test 6: Raise an error when line bounds are invalid."""
    file_path = tmp_path / "lines.txt"
    file_path.write_text("line 1\nline 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line_start"):
        asyncio.run(read_file(str(file_path), line_start=0))
    with pytest.raises(ValueError, match="line_end"):
        asyncio.run(read_file(str(file_path), line_start=3, line_end=1))


@pytest.mark.parametrize("line_end", [0, -1])
def test_read_invalid_line_end_without_start(tmp_path, line_end):
    with pytest.raises(ValueError, match="line_end"):
        asyncio.run(read_file(str(tmp_path / "file.txt"), line_end=line_end))


@pytest.mark.parametrize(
    ("bounds", "name"),
    [
        ({"line_start": "1"}, "line_start"),
        ({"line_end": 1.5}, "line_end"),
        ({"line_start": True}, "line_start"),
        ({"line_end": False}, "line_end"),
    ],
)
def test_read_invalid_line_bound_types(tmp_path, bounds, name):
    with pytest.raises(TypeError, match=f"{name} must be an integer"):
        asyncio.run(read_file(str(tmp_path / "file.txt"), **bounds))


@pytest.mark.parametrize("file_path", [None, 123])
def test_read_invalid_file_path_type(file_path):
    with pytest.raises(TypeError, match="file_path"):
        asyncio.run(read_file(file_path))


def test_read_nonexistent_file(tmp_path):
    """Test 7: Raise an error when the file does not exist."""
    file_path = tmp_path / "does_not_exist.txt"

    with pytest.raises(FileNotFoundError):
        asyncio.run(read_file(str(file_path)))


def test_read_directory_raises(tmp_path):
    """Test 8: Raise an error when the target path is a directory."""
    with pytest.raises(IsADirectoryError):
        asyncio.run(read_file(str(tmp_path)))


def test_read_binary_file_raises(tmp_path):
    """Test 9: Raise an error for non-UTF-8 binary files."""
    file_path = tmp_path / "image.bin"
    file_path.write_bytes(b"\x80\x81\x82\xff\x00")

    with pytest.raises(UnicodeDecodeError):
        asyncio.run(read_file(str(file_path)))


def test_read_permission_error_propagates(tmp_path, monkeypatch):
    def deny_read(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr("builtins.open", deny_read)
    with pytest.raises(PermissionError, match="access denied"):
        asyncio.run(read_file(str(tmp_path / "file.txt")))


def test_schema_contract():
    """Test 10: Verify tool schema matches expected contract."""
    assert SCHEMA["type"] == "function"
    assert SCHEMA["function"]["name"] == "read_file"
    assert SCHEMA["function"]["parameters"]["required"] == ["file_path"]
    assert set(SCHEMA["function"]["parameters"]["properties"].keys()) == {
        "file_path",
        "line_start",
        "line_end",
    }
    assert SCHEMA["function"]["parameters"]["properties"]["line_start"]["minimum"] == 1
    assert SCHEMA["function"]["parameters"]["properties"]["line_end"]["minimum"] == 1
