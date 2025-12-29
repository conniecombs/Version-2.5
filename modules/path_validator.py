# modules/path_validator.py
"""
Secure path validation to prevent path traversal and other file system attacks.
"""
import os
import pathlib
from typing import Optional, List
from loguru import logger
from . import config


class PathValidationError(Exception):
    """Raised when path validation fails"""
    pass


class PathValidator:
    """
    Validates file paths for security and correctness.
    Prevents path traversal, symlink attacks, and access to system directories.
    """

    # System directories that should never be accessed
    FORBIDDEN_DIRS_WINDOWS = [
        'C:\\Windows',
        'C:\\Program Files',
        'C:\\Program Files (x86)',
        'C:\\ProgramData',
        'C:\\System',
        'C:\\$',
    ]

    FORBIDDEN_DIRS_UNIX = [
        '/etc',
        '/sys',
        '/proc',
        '/dev',
        '/root',
        '/boot',
        '/bin',
        '/sbin',
        '/usr/bin',
        '/usr/sbin',
    ]

    @staticmethod
    def validate_input_path(path: str, must_exist: bool = True,
                           allow_directories: bool = True,
                           allow_files: bool = True) -> pathlib.Path:
        """
        Validate an input path (from drag-and-drop, CLI, file dialog, etc.)

        Args:
            path: The path to validate
            must_exist: If True, path must exist on filesystem
            allow_directories: If True, directories are allowed
            allow_files: If True, files are allowed

        Returns:
            Normalized pathlib.Path object

        Raises:
            PathValidationError: If validation fails
        """
        if not path or not isinstance(path, str):
            raise PathValidationError("Path must be a non-empty string")

        try:
            # Resolve to absolute path, following symlinks
            p = pathlib.Path(path).resolve(strict=must_exist)
        except (OSError, RuntimeError) as e:
            raise PathValidationError(f"Invalid path: {e}")

        # Check if path exists (if required)
        if must_exist and not p.exists():
            raise PathValidationError(f"Path does not exist: {path}")

        # Check if it's the right type
        if p.exists():
            if p.is_dir() and not allow_directories:
                raise PathValidationError(f"Directories not allowed: {path}")
            if p.is_file() and not allow_files:
                raise PathValidationError(f"Files not allowed: {path}")

        # Check for forbidden directories
        if PathValidator._is_forbidden_path(p):
            raise PathValidationError(f"Access to system directories is forbidden: {path}")

        # Warn about symlinks but allow them (they've been resolved)
        original_path = pathlib.Path(path)
        if original_path.exists() and original_path.is_symlink():
            target = original_path.readlink()
            logger.warning(f"Following symlink: {path} -> {target}")

            # Validate the symlink target
            if PathValidator._is_forbidden_path(target):
                raise PathValidationError(f"Symlink points to forbidden directory: {path} -> {target}")

        return p

    @staticmethod
    def validate_image_file(path: str) -> pathlib.Path:
        """
        Validate a path is a supported image file.

        Args:
            path: Path to image file

        Returns:
            Normalized pathlib.Path object

        Raises:
            PathValidationError: If not a valid image file
        """
        p = PathValidator.validate_input_path(
            path,
            must_exist=True,
            allow_directories=False,
            allow_files=True
        )

        # Check file extension
        if not p.suffix.lower() in config.SUPPORTED_EXTENSIONS:
            raise PathValidationError(
                f"Unsupported file type: {p.suffix}. "
                f"Supported: {', '.join(config.SUPPORTED_EXTENSIONS)}"
            )

        # Check file size (prevent loading huge files into memory)
        max_size = 100 * 1024 * 1024  # 100MB
        file_size = p.stat().st_size
        if file_size > max_size:
            raise PathValidationError(
                f"File too large: {file_size / (1024*1024):.1f}MB (max {max_size / (1024*1024)}MB)"
            )

        # Check if readable
        if not os.access(p, os.R_OK):
            raise PathValidationError(f"File not readable: {path}")

        return p

    @staticmethod
    def validate_directory(path: str) -> pathlib.Path:
        """
        Validate a path is an accessible directory.

        Args:
            path: Path to directory

        Returns:
            Normalized pathlib.Path object

        Raises:
            PathValidationError: If not a valid directory
        """
        p = PathValidator.validate_input_path(
            path,
            must_exist=True,
            allow_directories=True,
            allow_files=False
        )

        # Check if readable
        if not os.access(p, os.R_OK | os.X_OK):
            raise PathValidationError(f"Directory not accessible: {path}")

        return p

    @staticmethod
    def validate_output_path(path: str, create_parent: bool = False) -> pathlib.Path:
        """
        Validate an output path for writing.

        Args:
            path: Path where file will be written
            create_parent: If True, create parent directory if it doesn't exist

        Returns:
            Normalized pathlib.Path object

        Raises:
            PathValidationError: If path is not writable
        """
        p = pathlib.Path(path).resolve()

        # Check for forbidden directories
        if PathValidator._is_forbidden_path(p):
            raise PathValidationError(f"Cannot write to system directory: {path}")

        # Check parent directory
        parent = p.parent
        if not parent.exists():
            if create_parent:
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created output directory: {parent}")
                except OSError as e:
                    raise PathValidationError(f"Cannot create directory {parent}: {e}")
            else:
                raise PathValidationError(f"Parent directory does not exist: {parent}")

        # Check if parent is writable
        if not os.access(parent, os.W_OK):
            raise PathValidationError(f"Cannot write to directory: {parent}")

        return p

    @staticmethod
    def _is_forbidden_path(p: pathlib.Path) -> bool:
        """
        Check if path is in a forbidden directory.

        Args:
            p: Path to check

        Returns:
            True if path is forbidden
        """
        path_str = str(p).replace('\\', '/')

        # Check Windows forbidden dirs
        for forbidden in PathValidator.FORBIDDEN_DIRS_WINDOWS:
            forbidden_normalized = forbidden.replace('\\', '/')
            if path_str.startswith(forbidden_normalized):
                return True

        # Check Unix forbidden dirs
        for forbidden in PathValidator.FORBIDDEN_DIRS_UNIX:
            if path_str.startswith(forbidden):
                return True

        return False

    @staticmethod
    def scan_directory_for_images(directory: str, recursive: bool = True) -> List[pathlib.Path]:
        """
        Safely scan a directory for image files.

        Args:
            directory: Directory to scan
            recursive: If True, scan subdirectories

        Returns:
            List of validated image file paths

        Raises:
            PathValidationError: If directory is invalid
        """
        dir_path = PathValidator.validate_directory(directory)

        image_files = []

        try:
            if recursive:
                # Use rglob for recursive search
                for ext in config.SUPPORTED_EXTENSIONS:
                    image_files.extend(dir_path.rglob(f"*{ext}"))
            else:
                # Use glob for non-recursive search
                for ext in config.SUPPORTED_EXTENSIONS:
                    image_files.extend(dir_path.glob(f"*{ext}"))

            # Validate each file
            validated = []
            for img_path in image_files:
                try:
                    validated_path = PathValidator.validate_image_file(str(img_path))
                    validated.append(validated_path)
                except PathValidationError as e:
                    logger.warning(f"Skipping invalid file {img_path}: {e}")
                    continue

            return sorted(validated, key=lambda p: str(p).lower())

        except Exception as e:
            raise PathValidationError(f"Error scanning directory {directory}: {e}")

    @staticmethod
    def safe_filename(filename: str, max_length: int = 100) -> str:
        """
        Sanitize a filename to remove dangerous characters.

        Args:
            filename: Original filename
            max_length: Maximum length of result

        Returns:
            Safe filename string
        """
        # Remove or replace dangerous characters
        safe = ""
        for char in filename:
            if char.isalnum() or char in (' ', '_', '-', '.'):
                safe += char
            else:
                safe += '_'

        # Remove leading/trailing dots and spaces
        safe = safe.strip('. ')

        # Limit length
        if len(safe) > max_length:
            # Try to preserve extension
            parts = safe.rsplit('.', 1)
            if len(parts) == 2:
                name, ext = parts
                max_name_length = max_length - len(ext) - 1
                safe = name[:max_name_length] + '.' + ext
            else:
                safe = safe[:max_length]

        # Ensure not empty
        if not safe:
            safe = "unnamed"

        return safe
