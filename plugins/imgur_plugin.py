"""
Imgur image hosting plugin.

This plugin provides support for uploading images to Imgur.com using their API.

Requirements:
- Imgur Client ID (get from https://api.imgur.com/oauth2/addclient)

Documentation: https://apidocs.imgur.com/
"""

from pathlib import Path
from typing import Optional, Callable
import httpx
from loguru import logger

from modules.plugin_interface import ImageHostPlugin, UploadResult, UploadException


class ImgurPlugin(ImageHostPlugin):
    """
    Imgur image hosting plugin.

    Uploads images to Imgur using their public API.
    Supports anonymous and authenticated uploads.
    """

    # Plugin metadata
    name = "Imgur"
    version = "1.0.0"
    author = "Connie's Uploader Community"
    description = "Upload images to Imgur.com with gallery/album support"
    service_url = "https://imgur.com"

    # Capabilities
    supports_galleries = True
    supports_private = False  # Anonymous uploads are public
    requires_authentication = True
    max_file_size_mb = 20  # Imgur limit
    allowed_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff']
    max_concurrent_uploads = 5

    API_BASE = "https://api.imgur.com/3"

    def __init__(self, credentials: dict = None, config: dict = None):
        """
        Initialize Imgur plugin.

        Args:
            credentials: Must contain 'client_id' key
            config: Optional configuration
        """
        super().__init__(credentials, config)

        self.client_id = self.credentials.get('client_id', '')

        if not self.client_id:
            logger.warning("Imgur plugin initialized without client_id")

        # Create HTTP client with auth header
        self.client = httpx.Client(
            headers={
                'Authorization': f'Client-ID {self.client_id}'
            },
            timeout=60.0
        )

    def upload(
        self,
        file_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """
        Upload image to Imgur.

        Args:
            file_path: Path to image file
            progress_callback: Optional progress callback (not fully supported by Imgur API)

        Returns:
            UploadResult with image and thumbnail URLs

        Raises:
            UploadException: If upload fails
        """
        if not self.client_id:
            raise UploadException("Imgur client_id not configured")

        # Validate file
        is_valid, error = self.validate_file(file_path)
        if not is_valid:
            raise UploadException(error)

        try:
            # Read file
            with open(file_path, 'rb') as f:
                image_data = f.read()

            logger.debug(f"Uploading {file_path.name} to Imgur ({len(image_data)} bytes)")

            # Upload to Imgur
            response = self.client.post(
                f"{self.API_BASE}/image",
                files={'image': (file_path.name, image_data)},
                data={
                    'type': 'file',
                    'name': file_path.stem,
                    'title': file_path.stem
                }
            )

            # Check response
            if response.status_code not in (200, 201):
                error_msg = self._parse_error(response)
                raise UploadException(f"Imgur upload failed: {error_msg}")

            # Parse response
            data = response.json()

            if not data.get('success'):
                raise UploadException("Imgur API returned success=false")

            image_data = data['data']

            # Imgur provides multiple sizes, we'll use the full image and medium thumbnail
            image_url = image_data['link']

            # Generate thumbnail URL (Imgur CDN pattern)
            # e.g., https://i.imgur.com/abc123.jpg -> https://i.imgur.com/abc123m.jpg
            thumb_url = image_url
            if '.' in image_url:
                base, ext = image_url.rsplit('.', 1)
                thumb_url = f"{base}m.{ext}"  # 'm' suffix = medium thumbnail

            logger.info(f"Successfully uploaded to Imgur: {image_url}")

            return UploadResult(
                image_url=image_url,
                thumb_url=thumb_url,
                metadata={
                    'id': image_data.get('id'),
                    'deletehash': image_data.get('deletehash'),  # For deletion
                    'type': image_data.get('type'),
                    'width': image_data.get('width'),
                    'height': image_data.get('height'),
                    'size': image_data.get('size'),
                    'views': image_data.get('views', 0)
                }
            )

        except httpx.HTTPError as e:
            raise UploadException(f"Network error uploading to Imgur: {e}") from e
        except Exception as e:
            if isinstance(e, UploadException):
                raise
            raise UploadException(f"Unexpected error uploading to Imgur: {e}") from e

    def validate_credentials(self) -> bool:
        """
        Validate Imgur client ID by checking API credits.

        Returns:
            True if client_id is valid
        """
        if not self.client_id:
            return False

        try:
            response = self.client.get(f"{self.API_BASE}/credits")

            if response.status_code != 200:
                logger.warning(f"Imgur credential validation failed: {response.status_code}")
                return False

            data = response.json()
            if data.get('success'):
                # Log remaining credits for debugging
                credits = data.get('data', {})
                logger.debug(
                    f"Imgur credits: {credits.get('ClientRemaining')}/{credits.get('ClientLimit')} remaining"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error validating Imgur credentials: {e}")
            return False

    def create_gallery(self, gallery_name: str, image_urls: list) -> Optional[str]:
        """
        Create an Imgur album.

        Args:
            gallery_name: Album title
            image_urls: List of Imgur image URLs

        Returns:
            Album URL if successful

        Raises:
            UploadException: If album creation fails
        """
        if not self.supports_galleries:
            return None

        try:
            # Extract image IDs from URLs
            # e.g., https://i.imgur.com/abc123.jpg -> abc123
            image_ids = []
            for url in image_urls:
                # Handle both i.imgur.com and imgur.com URLs
                if '//' in url:
                    url = url.split('//')[-1]
                if '/' in url:
                    filename = url.split('/')[-1]
                    # Remove extension and thumbnail suffix
                    image_id = filename.split('.')[0].rstrip('mltsh')  # Remove size suffixes
                    image_ids.append(image_id)

            if not image_ids:
                raise UploadException("No valid image IDs found in URLs")

            logger.debug(f"Creating Imgur album '{gallery_name}' with {len(image_ids)} images")

            # Create album
            response = self.client.post(
                f"{self.API_BASE}/album",
                data={
                    'title': gallery_name,
                    'ids': ','.join(image_ids),  # Comma-separated IDs
                    'privacy': 'public'
                }
            )

            if response.status_code not in (200, 201):
                error_msg = self._parse_error(response)
                raise UploadException(f"Imgur album creation failed: {error_msg}")

            data = response.json()
            if not data.get('success'):
                raise UploadException("Imgur API returned success=false for album")

            album_id = data['data']['id']
            album_url = f"https://imgur.com/a/{album_id}"

            logger.info(f"Created Imgur album: {album_url}")
            return album_url

        except Exception as e:
            if isinstance(e, UploadException):
                raise
            logger.error(f"Error creating Imgur album: {e}")
            raise UploadException(f"Failed to create Imgur album: {e}") from e

    def delete_image(self, image_url: str, deletehash: str = None) -> bool:
        """
        Delete an uploaded image.

        Args:
            image_url: URL of image to delete
            deletehash: Delete hash from upload metadata (required)

        Returns:
            True if deletion successful

        Note:
            Requires the deletehash from the upload metadata.
        """
        if not deletehash:
            logger.warning("Cannot delete Imgur image without deletehash")
            return False

        try:
            response = self.client.delete(
                f"{self.API_BASE}/image/{deletehash}"
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info(f"Deleted Imgur image: {image_url}")
                    return True

            logger.warning(f"Failed to delete Imgur image: {response.status_code}")
            return False

        except Exception as e:
            logger.error(f"Error deleting Imgur image: {e}")
            return False

    def get_credential_fields(self) -> dict:
        """
        Return credential fields for UI.

        Returns:
            Dictionary of credential field metadata
        """
        return {
            'client_id': {
                'label': 'Imgur Client ID',
                'type': 'password',
                'required': True,
                'placeholder': 'Get from Imgur API dashboard',
                'help_url': 'https://api.imgur.com/oauth2/addclient',
                'help_text': (
                    'Register your application at api.imgur.com to get a Client ID. '
                    'Choose "OAuth 2 authorization without a callback URL" for desktop app.'
                )
            }
        }

    def get_upload_options(self) -> dict:
        """
        Return upload options for UI.

        Returns:
            Dictionary of upload option metadata
        """
        return {
            'title': {
                'label': 'Image Title',
                'type': 'text',
                'default': '',
                'help_text': 'Optional title for the image'
            },
            'description': {
                'label': 'Description',
                'type': 'text',
                'default': '',
                'help_text': 'Optional description'
            }
        }

    def _parse_error(self, response: httpx.Response) -> str:
        """
        Parse error message from Imgur API response.

        Args:
            response: HTTP response

        Returns:
            Error message string
        """
        try:
            data = response.json()
            if 'data' in data and 'error' in data['data']:
                return data['data']['error']
            if 'error' in data:
                return str(data['error'])
            return response.text[:200]
        except:
            return f"HTTP {response.status_code}"

    def cleanup(self):
        """Close HTTP client."""
        if self.client:
            try:
                self.client.close()
            except:
                pass
