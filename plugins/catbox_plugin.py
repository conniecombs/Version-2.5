"""
Catbox.moe image hosting plugin.

This plugin provides support for uploading images to Catbox.moe.
No authentication required for basic uploads.

Documentation: https://catbox.moe/faq.php
"""

from pathlib import Path
from typing import Optional, Callable
import httpx
from loguru import logger

from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException


class CatboxPlugin(ImageHostPlugin):
    """
    Catbox.moe image hosting plugin.

    Simple, anonymous file hosting. No registration required.
    """

    # Plugin metadata
    name = "Catbox"
    version = "1.0.0"
    author = "Connie's Uploader Community"
    description = "Upload images to Catbox.moe (anonymous, no registration)"
    service_url = "https://catbox.moe"

    # Capabilities
    supports_galleries = False  # Catbox doesn't have galleries
    supports_private = False
    requires_authentication = False  # Anonymous uploads
    max_file_size_mb = 200  # Catbox has generous limits
    allowed_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg']
    max_concurrent_uploads = 3  # Be nice to free services

    UPLOAD_URL = "https://catbox.moe/user/api.php"

    def __init__(self, credentials: dict = None, config: dict = None):
        """
        Initialize Catbox plugin.

        Args:
            credentials: Optional user hash for authenticated uploads
            config: Optional configuration
        """
        super().__init__(credentials, config)

        self.user_hash = self.credentials.get('user_hash', '')

        # Create HTTP client
        self.client = httpx.Client(timeout=120.0)  # Long timeout for large files

    def upload(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """
        Upload image to Catbox.

        Args:
            file_path: Path to image file
            progress_callback: Optional progress callback

        Returns:
            UploadResult with image URL

        Raises:
            UploadException: If upload fails
        """
        # Validate file
        is_valid, error = self.validate_file(file_path)
        if not is_valid:
            raise UploadException(error)

        try:
            logger.debug(f"Uploading {file_path.name} to Catbox")

            # Prepare upload data
            with open(file_path, 'rb') as f:
                files = {'fileToUpload': (file_path.name, f, 'image/*')}

                data = {
                    'reqtype': 'fileupload',
                }

                # Add user hash if available (for authenticated uploads)
                if self.user_hash:
                    data['userhash'] = self.user_hash

                # Upload
                response = self.client.post(
                    self.UPLOAD_URL,
                    files=files,
                    data=data
                )

            # Check response
            if response.status_code != 200:
                raise UploadException(f"Catbox upload failed: HTTP {response.status_code}")

            # Catbox returns the URL directly as plain text
            image_url = response.text.strip()

            # Validate URL
            if not image_url.startswith('https://'):
                raise UploadException(f"Unexpected Catbox response: {image_url[:100]}")

            logger.info(f"Successfully uploaded to Catbox: {image_url}")

            # Catbox doesn't provide separate thumbnails
            return UploadResult(
                image_url=image_url,
                thumb_url=image_url,  # Same as full image
                metadata={
                    'filename': file_path.name,
                    'service': 'catbox'
                }
            )

        except httpx.HTTPError as e:
            raise UploadException(f"Network error uploading to Catbox: {e}") from e
        except Exception as e:
            if isinstance(e, UploadException):
                raise
            raise UploadException(f"Unexpected error uploading to Catbox: {e}") from e

    def validate_credentials(self) -> bool:
        """
        Validate credentials (optional for Catbox).

        Returns:
            Always True since authentication is optional
        """
        # Catbox doesn't require authentication for basic uploads
        # If user hash is provided, we could validate it, but it's not critical
        if self.user_hash:
            logger.debug("Catbox user hash provided (not validated)")

        return True

    def delete_image(self, image_url: str) -> bool:
        """
        Delete an uploaded file (requires authentication).

        Args:
            image_url: URL of file to delete

        Returns:
            True if deletion successful

        Note:
            Requires user_hash in credentials
        """
        if not self.user_hash:
            logger.warning("Cannot delete Catbox file without user_hash")
            return False

        try:
            # Extract filename from URL
            # e.g., https://files.catbox.moe/abc123.jpg -> abc123.jpg
            filename = image_url.split('/')[-1]

            response = self.client.post(
                self.UPLOAD_URL,
                data={
                    'reqtype': 'deletefiles',
                    'userhash': self.user_hash,
                    'files': filename
                }
            )

            if response.status_code == 200:
                result = response.text.strip()
                if result.lower() == 'files successfully deleted':
                    logger.info(f"Deleted Catbox file: {filename}")
                    return True

            logger.warning(f"Failed to delete Catbox file: {response.text}")
            return False

        except Exception as e:
            logger.error(f"Error deleting Catbox file: {e}")
            return False

    def get_credential_fields(self) -> dict:
        """
        Return credential fields for UI.

        Returns:
            Dictionary of credential field metadata
        """
        return {
            'user_hash': {
                'label': 'User Hash (optional)',
                'type': 'password',
                'required': False,
                'placeholder': 'Leave empty for anonymous uploads',
                'help_url': 'https://catbox.moe/',
                'help_text': (
                    'Optional: Register at catbox.moe and get your user hash '
                    'to track uploads and enable deletion. '
                    'Anonymous uploads work without this.'
                )
            }
        }

    def get_upload_options(self) -> dict:
        """
        Return upload options for UI.

        Returns:
            Dictionary of upload option metadata
        """
        return {}  # Catbox has no upload options

    def cleanup(self):
        """Close HTTP client."""
        if self.client:
            try:
                self.client.close()
            except:
                pass
