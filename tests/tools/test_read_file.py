import asyncio

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
    """Test 6: Return an error message when line bounds are invalid."""
    file_path = tmp_path / "lines.txt"
    file_path.write_text("line 1\nline 2\n", encoding="utf-8")

    zero_start = asyncio.run(read_file(str(file_path), line_start=0))
    inverted_range = asyncio.run(read_file(str(file_path), line_start=3, line_end=1))

    assert "Error" in zero_start
    assert "Error" in inverted_range


def test_read_nonexistent_file(tmp_path):
    """Test 7: Return an error message when the file does not exist."""
    file_path = tmp_path / "does_not_exist.txt"

    result = asyncio.run(read_file(str(file_path)))

    assert "Error" in result
    assert "does not exist" in result


def test_read_directory_returns_error(tmp_path):
    """Test 8: Return an error message when the target path is a directory."""
    result = asyncio.run(read_file(str(tmp_path)))

    assert "Error" in result
    assert "directory" in result


def test_read_binary_file_returns_error(tmp_path):
    """Test 9: Return an error message for non-UTF-8 binary files."""
    file_path = tmp_path / "image.bin"
    file_path.write_bytes(b"\x80\x81\x82\xff\x00")

    result = asyncio.run(read_file(str(file_path)))

    assert "Error" in result
    assert "UTF-8" in result


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
