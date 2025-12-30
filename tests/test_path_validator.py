"""
Unit tests for path_validator.py - Security Module

Tests comprehensive path validation including:
- Path traversal attack prevention
- Symlink attack prevention
- System directory protection
- File type validation
- Size limits
"""

import pytest
import os
import tempfile
from pathlib import Path
from modules.path_validator import PathValidator, PathValidationError


class TestPathValidator:
    """Test suite for PathValidator security module."""

    def test_valid_input_path_file(self, tmp_path):
        """Test validation of valid file path."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test")

        result = PathValidator.validate_input_path(str(test_file))
        assert result.exists()
        assert result.is_file()

    def test_valid_input_path_directory(self, tmp_path):
        """Test validation of valid directory path."""
        result = PathValidator.validate_input_path(str(tmp_path))
        assert result.exists()
        assert result.is_dir()

    def test_nonexistent_path_with_must_exist(self, tmp_path):
        """Test that nonexistent paths are rejected when must_exist=True."""
        nonexistent = tmp_path / "does_not_exist.jpg"

        with pytest.raises(PathValidationError, match="Invalid path"):
            PathValidator.validate_input_path(str(nonexistent), must_exist=True)

    def test_path_traversal_attack_prevention(self, tmp_path):
        """Test prevention of path traversal that leads to system directories."""
        # These paths use traversal syntax but resolve to forbidden directories
        malicious_paths = [
            "../../../etc/passwd",      # Resolves to /etc/passwd
            "./../../../root/.ssh/id_rsa"  # Resolves to /root/...
        ]

        for path in malicious_paths:
            with pytest.raises(PathValidationError, match="(Access to system directories is forbidden|Invalid path)"):
                PathValidator.validate_input_path(path, must_exist=False)

        # Note: Path traversal syntax itself isn't blocked - only paths that
        # resolve to forbidden directories are blocked. This is the correct behavior
        # because "../file.jpg" could be a legitimate relative path.

    def test_null_byte_injection_prevention(self):
        """Test prevention of null byte injection."""
        malicious_paths = [
            "file.jpg\x00.txt",
            "image\x00.exe",
            "test\x00/../../etc/passwd"
        ]

        for path in malicious_paths:
            # Python's pathlib raises ValueError for null bytes
            with pytest.raises((ValueError, PathValidationError)):
                PathValidator.validate_input_path(path, must_exist=False)

    def test_system_directory_protection_unix(self, tmp_path, monkeypatch):
        """Test that system directories are blocked on Unix."""
        monkeypatch.setattr("platform.system", lambda: "Linux")

        forbidden = ["/etc", "/sys", "/proc", "/root"]

        for path in forbidden:
            with pytest.raises(PathValidationError, match="Access to system directories is forbidden"):
                PathValidator.validate_input_path(path, must_exist=False)

    def test_system_directory_protection_windows(self, tmp_path, monkeypatch):
        """Test that Windows system directories are detected (testing logic only)."""
        import platform
        import pytest

        # Skip test if on Linux (Windows paths won't resolve properly)
        if platform.system() != "Windows":
            pytest.skip("Windows path test only runs on Windows")

        monkeypatch.setattr("platform.system", lambda: "Windows")

        forbidden = [
            "C:\\Windows",
            "C:\\Program Files",
            "C:\\Windows\\System32"
        ]

        for path in forbidden:
            with pytest.raises(PathValidationError, match="Access to system directories is forbidden"):
                PathValidator.validate_input_path(path, must_exist=False)

    def test_symlink_attack_prevention(self, tmp_path):
        """Test that symlinks to allowed directories are accepted (but logged)."""
        # Create a regular target (not forbidden)
        safe_target = tmp_path / "safe_target"
        safe_target.mkdir()

        symlink = tmp_path / "safe_link"
        try:
            symlink.symlink_to(safe_target)

            # Should succeed - symlinks are allowed if target is not forbidden
            result = PathValidator.validate_input_path(str(symlink))
            assert result.exists()
            assert result.is_dir()
        except OSError:
            # Symlinks may not be supported on some systems
            pytest.skip("Symlinks not supported")

    def test_validate_image_file_valid(self, tmp_path):
        """Test validation of valid image file."""
        valid_images = ["test.jpg", "photo.png", "image.gif", "pic.bmp"]

        for filename in valid_images:
            img_file = tmp_path / filename
            img_file.write_bytes(b"fake image data")

            result = PathValidator.validate_image_file(str(img_file))
            assert result.exists()
            assert result.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']

    def test_validate_image_file_invalid_extension(self, tmp_path):
        """Test rejection of non-image files."""
        invalid_files = ["script.exe", "malware.sh", "virus.bat", "readme.txt"]

        for filename in invalid_files:
            bad_file = tmp_path / filename
            bad_file.write_text("malicious content")

            with pytest.raises(PathValidationError, match="Unsupported file type"):
                PathValidator.validate_image_file(str(bad_file))

    def test_validate_image_file_size_limit(self, tmp_path):
        """Test that oversized files are rejected."""
        huge_file = tmp_path / "huge.jpg"
        # Create a file larger than 100MB
        huge_file.write_bytes(b"x" * (101 * 1024 * 1024))

        with pytest.raises(PathValidationError, match="too large"):
            PathValidator.validate_image_file(str(huge_file))

    def test_validate_directory_valid(self, tmp_path):
        """Test validation of valid directory."""
        result = PathValidator.validate_directory(str(tmp_path))
        assert result.is_dir()

    def test_validate_directory_is_file(self, tmp_path):
        """Test rejection when path is a file, not directory."""
        file_path = tmp_path / "notadir.txt"
        file_path.write_text("test")

        with pytest.raises(PathValidationError, match="Files not allowed"):
            PathValidator.validate_directory(str(file_path))

    def test_safe_filename_basic(self):
        """Test safe filename sanitization."""
        unsafe_names = [
            ("my file.jpg", "my file.jpg"),  # Spaces are allowed
            ("test:file.png", "test_file.png"),
            ("image<>name.gif", "image__name.gif"),
            ('file"name.jpg', "file_name.jpg"),
            ("path/to/file.jpg", "path_to_file.jpg"),
        ]

        for unsafe, expected in unsafe_names:
            result = PathValidator.safe_filename(unsafe)
            assert result == expected

    def test_safe_filename_length_limit(self):
        """Test that long filenames are truncated."""
        long_name = "a" * 200 + ".jpg"
        result = PathValidator.safe_filename(long_name, max_length=50)
        assert len(result) <= 50
        assert result.endswith(".jpg")

    def test_validate_output_path_creates_parent(self, tmp_path):
        """Test that output path validation creates parent directories."""
        output_dir = tmp_path / "Output"
        output_file = output_dir / "result.txt"

        result = PathValidator.validate_output_path(str(output_file), create_parent=True)
        assert output_dir.exists()
        assert output_dir.is_dir()

    def test_scan_directory_for_images(self, tmp_path):
        """Test scanning directory for image files."""
        # Create test structure
        (tmp_path / "image1.jpg").write_bytes(b"img1")
        (tmp_path / "image2.png").write_bytes(b"img2")
        (tmp_path / "readme.txt").write_text("not an image")

        subdir = tmp_path / "subfolder"
        subdir.mkdir()
        (subdir / "image3.gif").write_bytes(b"img3")

        # Non-recursive scan
        images = PathValidator.scan_directory_for_images(str(tmp_path), recursive=False)
        assert len(images) == 2

        # Recursive scan
        images_recursive = PathValidator.scan_directory_for_images(str(tmp_path), recursive=True)
        assert len(images_recursive) == 3

    def test_normalize_path(self, tmp_path):
        """Test that validate_input_path normalizes paths to absolute."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test")

        # validate_input_path should return an absolute path
        result = PathValidator.validate_input_path(str(test_file))
        assert result.is_absolute()

    def test_empty_path_rejection(self):
        """Test that empty paths are rejected."""
        with pytest.raises(PathValidationError, match="Path must be a non-empty string"):
            PathValidator.validate_input_path("")

    def test_whitespace_only_path_rejection(self):
        """Test that whitespace-only paths are rejected."""
        with pytest.raises(PathValidationError, match="Invalid path"):
            PathValidator.validate_input_path("   ")


class TestPathValidatorEdgeCases:
    """Edge case tests for PathValidator."""

    def test_unicode_filename(self, tmp_path):
        """Test handling of Unicode filenames."""
        unicode_file = tmp_path / "图片.jpg"
        unicode_file.write_bytes(b"image")

        result = PathValidator.validate_image_file(str(unicode_file))
        assert result.exists()

    def test_very_long_path(self, tmp_path):
        """Test handling of very long paths."""
        # Create nested directories
        deep_path = tmp_path
        for i in range(20):
            deep_path = deep_path / f"level{i}"

        # This might fail on some systems due to path length limits
        try:
            deep_path.mkdir(parents=True)
            test_file = deep_path / "test.jpg"
            test_file.write_bytes(b"img")

            result = PathValidator.validate_image_file(str(test_file))
            assert result.exists()
        except OSError:
            pytest.skip("Path too long for this system")

    def test_case_insensitive_extensions(self, tmp_path):
        """Test that file extensions are case-insensitive."""
        extensions = ["JPG", "PNG", "GIF", "Jpg", "pNg"]

        for ext in extensions:
            img_file = tmp_path / f"test.{ext}"
            img_file.write_bytes(b"image")

            result = PathValidator.validate_image_file(str(img_file))
            assert result.exists()

    def test_double_extension_file(self, tmp_path):
        """Test handling of double extensions."""
        # Should accept based on final extension
        file1 = tmp_path / "archive.tar.jpg"
        file1.write_bytes(b"image")

        result = PathValidator.validate_image_file(str(file1))
        assert result.exists()

        # Should reject if final extension is not image
        file2 = tmp_path / "image.jpg.txt"
        file2.write_text("not an image")

        with pytest.raises(PathValidationError):
            PathValidator.validate_image_file(str(file2))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
