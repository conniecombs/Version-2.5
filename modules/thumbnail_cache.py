# modules/thumbnail_cache.py
"""
Thumbnail Cache - Performance Optimization

Caches generated thumbnails to avoid redundant PIL operations.
Uses LRU eviction strategy and file modification time tracking.
"""

import os
import hashlib
import pickle
from pathlib import Path
from typing import Optional, Tuple, Any
from collections import OrderedDict
from PIL import Image
from loguru import logger


class ThumbnailCache:
    """
    In-memory LRU cache for image thumbnails with optional disk persistence.

    Performance Benefits:
    - Avoids redundant PIL Image.open() and thumbnail() operations
    - Significantly faster when re-adding previously processed files
    - Reduces memory churn from temporary PIL objects

    Cache Key Strategy:
    - Uses file path + modification time to detect changes
    - Automatically invalidates cache when file is modified
    """

    def __init__(self, max_memory_items: int = 1000, disk_cache_dir: Optional[str] = None):
        """
        Initialize thumbnail cache.

        Args:
            max_memory_items: Maximum thumbnails to keep in memory (LRU eviction)
            disk_cache_dir: Optional directory for persistent disk cache
        """
        self.max_memory_items = max_memory_items
        self.disk_cache_dir = disk_cache_dir
        self.memory_cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

        # Create disk cache directory if specified
        if disk_cache_dir:
            Path(disk_cache_dir).mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, file_path: str, mtime: float) -> str:
        """
        Generate cache key from file path and modification time.

        Args:
            file_path: Absolute path to image file
            mtime: File modification time

        Returns:
            Cache key string
        """
        # Use hash of path + mtime for shorter keys
        key_data = f"{file_path}:{mtime}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _get_disk_cache_path(self, cache_key: str) -> Optional[Path]:
        """Get disk cache file path for a cache key."""
        if not self.disk_cache_dir:
            return None
        return Path(self.disk_cache_dir) / f"{cache_key}.thumb"

    def get(self, file_path: str, thumbnail_size: Tuple[int, int]) -> Optional[Any]:
        """
        Retrieve cached thumbnail for a file.

        Args:
            file_path: Path to image file
            thumbnail_size: Expected thumbnail size (for validation)

        Returns:
            PIL Image object if cached, None if cache miss
        """
        try:
            # Get file modification time
            mtime = os.path.getmtime(file_path)
            cache_key = self._get_cache_key(file_path, mtime)

            # Try memory cache first (fast path)
            if cache_key in self.memory_cache:
                pil_image, cached_mtime = self.memory_cache[cache_key]

                # Verify mtime hasn't changed
                if cached_mtime == mtime:
                    # Move to end (mark as recently used)
                    self.memory_cache.move_to_end(cache_key)
                    self.hits += 1
                    logger.debug(f"Thumbnail cache HIT (memory): {file_path}")
                    return pil_image
                else:
                    # File changed, invalidate cache entry
                    del self.memory_cache[cache_key]

            # Try disk cache (slower path)
            if self.disk_cache_dir:
                disk_path = self._get_disk_cache_path(cache_key)
                if disk_path and disk_path.exists():
                    try:
                        with open(disk_path, 'rb') as f:
                            pil_image = pickle.load(f)

                        # Store in memory cache for next access
                        self._store_in_memory(cache_key, pil_image, mtime)

                        self.hits += 1
                        logger.debug(f"Thumbnail cache HIT (disk): {file_path}")
                        return pil_image
                    except Exception as e:
                        logger.warning(f"Failed to load disk cache for {file_path}: {e}")
                        # Remove corrupted cache file
                        disk_path.unlink(missing_ok=True)

            # Cache miss
            self.misses += 1
            logger.debug(f"Thumbnail cache MISS: {file_path}")
            return None

        except Exception as e:
            logger.error(f"Error accessing thumbnail cache for {file_path}: {e}")
            return None

    def put(self, file_path: str, pil_image: Any, thumbnail_size: Tuple[int, int]):
        """
        Store thumbnail in cache.

        Args:
            file_path: Path to original image file
            pil_image: Generated PIL thumbnail image
            thumbnail_size: Size of thumbnail (for metadata)
        """
        try:
            mtime = os.path.getmtime(file_path)
            cache_key = self._get_cache_key(file_path, mtime)

            # Store in memory
            self._store_in_memory(cache_key, pil_image, mtime)

            # Store on disk if enabled
            if self.disk_cache_dir:
                try:
                    disk_path = self._get_disk_cache_path(cache_key)
                    with open(disk_path, 'wb') as f:
                        pickle.dump(pil_image, f, protocol=pickle.HIGHEST_PROTOCOL)
                    logger.debug(f"Thumbnail cached to disk: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to write disk cache for {file_path}: {e}")

        except Exception as e:
            logger.error(f"Error storing thumbnail in cache for {file_path}: {e}")

    def _store_in_memory(self, cache_key: str, pil_image: Any, mtime: float):
        """Store thumbnail in memory cache with LRU eviction."""
        # Add to cache
        self.memory_cache[cache_key] = (pil_image, mtime)
        self.memory_cache.move_to_end(cache_key)

        # Evict oldest if over limit (LRU)
        while len(self.memory_cache) > self.max_memory_items:
            oldest_key, _ = self.memory_cache.popitem(last=False)
            logger.debug(f"Evicted thumbnail from memory cache: {oldest_key}")

    def clear(self):
        """Clear all cached thumbnails from memory."""
        self.memory_cache.clear()
        logger.info("Thumbnail cache cleared")

    def clear_disk_cache(self):
        """Clear all cached thumbnails from disk."""
        if not self.disk_cache_dir:
            return

        try:
            cache_path = Path(self.disk_cache_dir)
            if cache_path.exists():
                for cache_file in cache_path.glob("*.thumb"):
                    cache_file.unlink()
                logger.info("Disk thumbnail cache cleared")
        except Exception as e:
            logger.error(f"Failed to clear disk cache: {e}")

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with hit/miss rates and cache size
        """
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0

        return {
            'hits': self.hits,
            'misses': self.misses,
            'total_requests': total,
            'hit_rate_percent': round(hit_rate, 2),
            'memory_cache_size': len(self.memory_cache),
            'max_memory_items': self.max_memory_items,
        }

    def log_stats(self):
        """Log cache performance statistics."""
        stats = self.get_stats()
        logger.info(
            f"Thumbnail Cache Stats: "
            f"{stats['hit_rate_percent']}% hit rate "
            f"({stats['hits']} hits, {stats['misses']} misses), "
            f"{stats['memory_cache_size']} items in memory"
        )


# Global singleton instance
_thumbnail_cache: Optional[ThumbnailCache] = None


def get_thumbnail_cache() -> ThumbnailCache:
    """
    Get the global thumbnail cache instance.

    Returns:
        ThumbnailCache singleton
    """
    global _thumbnail_cache
    if _thumbnail_cache is None:
        # Check if disk caching is enabled in config
        try:
            from .config_loader import get_config_loader
            config = get_config_loader().config
            # Disk cache disabled by default for now (can enable via config later)
            disk_cache_dir = None
        except:
            disk_cache_dir = None

        _thumbnail_cache = ThumbnailCache(
            max_memory_items=1000,
            disk_cache_dir=disk_cache_dir
        )
    return _thumbnail_cache


def clear_thumbnail_cache():
    """Clear the global thumbnail cache."""
    global _thumbnail_cache
    if _thumbnail_cache:
        _thumbnail_cache.clear()
