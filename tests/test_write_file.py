import asyncio
from pathlib import Path

from src.tools.write_file import write_file


def test_create_file(tmp_path):
    """Test 1: Create a new file."""

    file_path = tmp_path / "hello.txt"

    asyncio.run(write_file(str(file_path), "Hello OPHELIA!"))

    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "Hello OPHELIA!"


def test_create_parent_directories(tmp_path):
    """Test 2: Create missing directories automatically."""

    file_path = tmp_path / "folder1" / "folder2" / "hello.txt"

    asyncio.run(write_file(str(file_path), "Hello!"))

    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "Hello!"


def test_overwrite_file(tmp_path):
    """Test 3: Overwrite an existing file."""

    file_path = tmp_path / "hello.txt"
    file_path.write_text("Old content", encoding="utf-8")

    asyncio.run(write_file(str(file_path), "New content"))

    assert file_path.read_text(encoding="utf-8") == "New content"


def test_empty_content(tmp_path):
    """Test 4: Write an empty file."""

    file_path = tmp_path / "empty.txt"

    asyncio.run(write_file(str(file_path), ""))

    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == ""


def test_unicode_content(tmp_path):
    """Test 5: Write special characters."""

    file_path = tmp_path / "unicode.txt"
    content = "Bonjour ! é è à 🚀"

    asyncio.run(write_file(str(file_path), content))

    assert file_path.read_text(encoding="utf-8") == content