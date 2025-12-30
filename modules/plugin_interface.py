"""
Plugin interface for custom image hosting services.

This module provides the base class that all image hosting plugins must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, Callable
from pathlib import Path
import httpx
from dataclasses import dataclass


class UploadException(Exception):
    """Exception raised when upload fails"""
    pass


@dataclass
class UploadResult:
    """Result of an upload operation"""
    image_url: str
    thumb_url: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ImageHostPlugin(ABC):
    """
    Base class for image hosting service plugins.

    All plugins must inherit from this class and implement the required methods.
    The plugin system will automatically discover and load plugins that follow
    this interface.

    Example:
        class MyServicePlugin(ImageHostPlugin):
            name = "MyService"
            version = "1.0.0"

            def upload(self, file_path, progress_callback=None):
                # Implementation
                pass

            def validate_credentials(self):
                # Implementation
                pass
    """

    # Required metadata - subclasses must define these
    name: str = ""
    version: str = "1.0.0"
    author: str = ""
    description: str = ""
    service_url: str = ""

    # Service capabilities
    supports_galleries: bool = False
    supports_private: bool = False
    requires_authentication: bool = False
    max_file_size_mb: int = 10
    allowed_formats: list = None

    # Threading configuration
    max_concurrent_uploads: int = 3

    def __init__(self, credentials: Dict = None, config: Dict = None):
        """
        Initialize plugin with credentials and configuration.

        Args:
            credentials: Dictionary of credentials (API keys, passwords, etc.)
            config: Optional configuration dictionary
        """
        self.credentials = credentials or {}
        self.config = config or {}
        self.client: Optional[httpx.Client] = None

        # Set default allowed formats if not specified
        if self.allowed_formats is None:
            self.allowed_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']

    @abstractmethod
    def upload(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """
        Upload an image to the hosting service.

        Args:
            file_path: Path to the image file to upload
            progress_callback: Optional callback function(bytes_sent, total_bytes)
                             to report upload progress

        Returns:
            UploadResult containing image_url and thumb_url

        Raises:
            UploadException: If upload fails for any reason

        Example:
            def upload(self, file_path, progress_callback=None):
                with open(file_path, 'rb') as f:
                    response = self.client.post(
                        'https://api.example.com/upload',
                        files={'image': f}
                    )

                data = response.json()
                return UploadResult(
                    image_url=data['url'],
                    thumb_url=data['thumbnail']
                )
        """
        pass

    @abstractmethod
    def validate_credentials(self) -> bool:
        """
        Validate the provided credentials.

        This method should verify that the credentials are correct by making
        a test API call or checking authentication.

        Returns:
            True if credentials are valid, False otherwise

        Example:
            def validate_credentials(self):
                try:
                    response = self.client.get('https://api.example.com/auth/check')
                    return response.status_code == 200
                except:
                    return False
        """
        pass

    def get_credential_fields(self) -> Dict[str, Dict]:
        """
        Return required credential fields for UI generation.

        The UI will automatically generate input fields based on this metadata.

        Returns:
            Dictionary mapping field names to field metadata:
            {
                'field_name': {
                    'label': 'Display Label',
                    'type': 'text' | 'password' | 'email',
                    'required': True | False,
                    'placeholder': 'Optional placeholder text',
                    'help_url': 'Optional help URL',
                    'help_text': 'Optional help text'
                }
            }

        Example:
            def get_credential_fields(self):
                return {
                    'api_key': {
                        'label': 'API Key',
                        'type': 'password',
                        'required': True,
                        'help_url': 'https://example.com/api',
                        'help_text': 'Get your API key from the dashboard'
                    },
                    'username': {
                        'label': 'Username',
                        'type': 'text',
                        'required': False,
                        'placeholder': 'optional'
                    }
                }
        """
        return {}

    def create_gallery(
        self,
        gallery_name: str,
        image_urls: list
    ) -> Optional[str]:
        """
        Create a gallery/album with uploaded images (optional).

        Args:
            gallery_name: Name for the gallery
            image_urls: List of uploaded image URLs to include

        Returns:
            Gallery URL if successful, None if not supported or failed

        Note:
            This method is only called if supports_galleries is True.
            Default implementation returns None.
        """
        if not self.supports_galleries:
            return None
        return None

    def delete_image(self, image_url: str) -> bool:
        """
        Delete an uploaded image (optional).

        Args:
            image_url: URL of the image to delete

        Returns:
            True if deletion successful, False otherwise

        Note:
            Default implementation returns False (not supported).
        """
        return False

    def validate_file(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Validate that a file can be uploaded.

        Args:
            file_path: Path to file to validate

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is None

        Note:
            Default implementation checks file size and format.
            Subclasses can override for custom validation.
        """
        # Check file exists
        if not file_path.exists():
            return False, "File does not exist"

        # Check file extension
        ext = file_path.suffix.lower().lstrip('.')
        if ext not in self.allowed_formats:
            return False, f"Format '{ext}' not supported. Allowed: {', '.join(self.allowed_formats)}"

        # Check file size
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_file_size_mb:
            return False, f"File too large ({size_mb:.1f}MB). Max: {self.max_file_size_mb}MB"

        return True, None

    def get_upload_options(self) -> Dict[str, Dict]:
        """
        Return available upload options for UI generation.

        Returns:
            Dictionary mapping option names to metadata:
            {
                'option_name': {
                    'label': 'Display Label',
                    'type': 'bool' | 'choice' | 'text',
                    'default': default_value,
                    'choices': [...] (for choice type),
                    'help_text': 'Optional help text'
                }
            }

        Example:
            def get_upload_options(self):
                return {
                    'private': {
                        'label': 'Make Private',
                        'type': 'bool',
                        'default': False,
                        'help_text': 'Only you can view the image'
                    },
                    'quality': {
                        'label': 'Image Quality',
                        'type': 'choice',
                        'choices': ['original', 'high', 'medium'],
                        'default': 'original'
                    }
                }
        """
        return {}

    def cleanup(self):
        """
        Cleanup resources (close connections, etc.).

        Called when the plugin is being unloaded or app is closing.
        Subclasses should override to clean up any resources.
        """
        if self.client:
            try:
                self.client.close()
            except:
                pass

    def __str__(self):
        return f"{self.name} v{self.version}"

    def __repr__(self):
        return f"<ImageHostPlugin: {self.name} v{self.version}>"
