"""
Unit tests for thumbnail_cache.py - Performance Module

Tests LRU caching, eviction, hit/miss tracking, and persistence.
"""

import pytest
import os
import tempfile
from pathlib import Path
from PIL import Image
from modules.thumbnail_cache import ThumbnailCache


class TestThumbnailCache:
    """Test suite for ThumbnailCache."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a fresh cache instance for each test."""
        return ThumbnailCache(max_memory_items=5, disk_cache_dir=None)

    @pytest.fixture
    def test_image(self, tmp_path):
        """Create a test image file."""
        img_path = tmp_path / "test.jpg"
        img = Image.new('RGB', (100, 100), color='red')
        img.save(img_path)
        return str(img_path)

    def test_cache_miss_on_first_access(self, cache, test_image):
        """Test that first access is a cache miss."""
        result = cache.get(test_image, (50, 50))
        assert result is None
        assert cache.misses == 1
        assert cache.hits == 0

    def test_cache_hit_after_put(self, cache, test_image):
        """Test that cached items can be retrieved."""
        # Create thumbnail
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cached_img = img.copy()

        # Store in cache
        cache.put(test_image, cached_img, (50, 50))

        # Retrieve from cache
        result = cache.get(test_image, (50, 50))
        assert result is not None
        assert cache.hits == 1
        assert cache.misses == 0

    def test_lru_eviction(self, cache, tmp_path):
        """Test that LRU eviction works correctly."""
        # Cache can hold 5 items
        images = []
        for i in range(7):
            img_path = tmp_path / f"image{i}.jpg"
            img = Image.new('RGB', (100, 100), color='red')
            img.save(img_path)
            images.append(str(img_path))

        # Add 7 items to cache (max is 5)
        for i, img_path in enumerate(images):
            img = Image.new('RGB', (50, 50), color='blue')
            cache.put(img_path, img, (50, 50))

        # Cache should have exactly 5 items (oldest 2 evicted)
        stats = cache.get_stats()
        assert stats['memory_cache_size'] == 5

        # First two items should be evicted
        assert cache.get(images[0], (50, 50)) is None  # Miss
        assert cache.get(images[1], (50, 50)) is None  # Miss

        # Last 5 items should still be cached
        for img_path in images[2:]:
            assert cache.get(img_path, (50, 50)) is not None  # Hit

    def test_cache_invalidation_on_file_modification(self, cache, test_image):
        """Test that cache is invalidated when file is modified."""
        # Cache the original
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cache.put(test_image, img.copy(), (50, 50))

        # Modify the file
        img_new = Image.new('RGB', (100, 100), color='blue')
        img_new.save(test_image)

        # Should be a cache miss (mtime changed)
        result = cache.get(test_image, (50, 50))
        assert result is None
        assert cache.misses == 1

    def test_cache_stats_accuracy(self, cache, test_image):
        """Test that cache statistics are accurate."""
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cached_img = img.copy()

        # Start with clean stats
        stats = cache.get_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        assert stats['hit_rate_percent'] == 0

        # Cache miss
        cache.get(test_image, (50, 50))

        # Add to cache
        cache.put(test_image, cached_img, (50, 50))

        # Cache hit
        cache.get(test_image, (50, 50))
        cache.get(test_image, (50, 50))

        # Check stats
        stats = cache.get_stats()
        assert stats['hits'] == 2
        assert stats['misses'] == 1
        assert stats['total_requests'] == 3
        assert stats['hit_rate_percent'] == pytest.approx(66.67, rel=0.1)

    def test_clear_cache(self, cache, test_image):
        """Test that clearing cache works."""
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cache.put(test_image, img.copy(), (50, 50))

        # Verify cache has content
        result = cache.get(test_image, (50, 50))
        assert result is not None
        assert cache.get_stats()['memory_cache_size'] == 1
        assert cache.hits == 1

        cache.clear()

        assert cache.get_stats()['memory_cache_size'] == 0
        # Stats counters persist after clear
        assert cache.hits == 1

    def test_cache_key_generation(self, cache, test_image):
        """Test that cache keys are generated correctly."""
        img = Image.open(test_image)
        img.thumbnail((50, 50))

        # Same file should generate same key
        mtime = os.path.getmtime(test_image)
        key1 = cache._get_cache_key(test_image, mtime)
        key2 = cache._get_cache_key(test_image, mtime)
        assert key1 == key2

        # Different mtime should generate different key
        key3 = cache._get_cache_key(test_image, mtime + 1)
        assert key1 != key3

    def test_multiple_cache_instances_independent(self, tmp_path, test_image):
        """Test that multiple cache instances are independent."""
        cache1 = ThumbnailCache(max_memory_items=10)
        cache2 = ThumbnailCache(max_memory_items=10)

        img = Image.open(test_image)
        img.thumbnail((50, 50))

        # Add to cache1
        cache1.put(test_image, img.copy(), (50, 50))

        # Should be in cache1 but not cache2
        assert cache1.get(test_image, (50, 50)) is not None
        assert cache2.get(test_image, (50, 50)) is None

    def test_zero_max_items_works(self, test_image):
        """Test that cache with max_items=0 still works (no caching)."""
        cache = ThumbnailCache(max_memory_items=0)

        img = Image.open(test_image)
        img.thumbnail((50, 50))

        cache.put(test_image, img.copy(), (50, 50))

        # Nothing should be cached
        assert cache.get_stats()['memory_cache_size'] == 0


class TestThumbnailCacheDiskPersistence:
    """Test disk persistence functionality."""

    @pytest.fixture
    def cache_with_disk(self, tmp_path):
        """Create cache with disk persistence enabled."""
        disk_dir = tmp_path / "cache"
        return ThumbnailCache(max_memory_items=5, disk_cache_dir=str(disk_dir))

    @pytest.fixture
    def test_image(self, tmp_path):
        """Create a test image file."""
        img_path = tmp_path / "test.jpg"
        img = Image.new('RGB', (100, 100), color='red')
        img.save(img_path)
        return str(img_path)

    def test_disk_cache_creation(self, cache_with_disk, test_image):
        """Test that disk cache directory is created."""
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cache_with_disk.put(test_image, img.copy(), (50, 50))

        # Check that cache directory exists
        assert Path(cache_with_disk.disk_cache_dir).exists()

    def test_disk_cache_persistence(self, tmp_path, test_image):
        """Test that cache persists across instances."""
        disk_dir = tmp_path / "cache"

        # Create first cache and add item
        cache1 = ThumbnailCache(max_memory_items=5, disk_cache_dir=str(disk_dir))
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cache1.put(test_image, img.copy(), (50, 50))

        # Create new cache instance with same disk dir
        cache2 = ThumbnailCache(max_memory_items=5, disk_cache_dir=str(disk_dir))

        # Should load from disk (cache miss in memory, but hit on disk)
        result = cache2.get(test_image, (50, 50))
        assert result is not None

    def test_clear_disk_cache(self, cache_with_disk, test_image):
        """Test that disk cache can be cleared."""
        img = Image.open(test_image)
        img.thumbnail((50, 50))
        cache_with_disk.put(test_image, img.copy(), (50, 50))

        # Clear disk cache
        cache_with_disk.clear_disk_cache()

        # Directory should be empty
        cache_dir = Path(cache_with_disk.disk_cache_dir)
        assert len(list(cache_dir.glob("*.thumb"))) == 0


class TestThumbnailCachePerformance:
    """Performance-related tests."""

    def test_large_cache_performance(self, tmp_path):
        """Test cache with large number of items."""
        cache = ThumbnailCache(max_memory_items=1000)

        # Add 1000 items
        for i in range(1000):
            img_path = tmp_path / f"image{i}.jpg"
            img = Image.new('RGB', (10, 10), color='red')
            img.save(img_path)

            thumb = Image.new('RGB', (5, 5), color='blue')
            cache.put(str(img_path), thumb, (5, 5))

        # All should be cached
        assert cache.get_stats()['memory_cache_size'] == 1000

        # Retrieve should be fast (LRU ordered dict lookup)
        test_path = str(tmp_path / "image500.jpg")
        result = cache.get(test_path, (5, 5))
        assert result is not None

    def test_cache_hit_moves_to_end(self, tmp_path):
        """Test that cache hits move items to end (LRU)."""
        cache = ThumbnailCache(max_memory_items=3)

        # Add 3 items
        paths = []
        for i in range(3):
            img_path = tmp_path / f"image{i}.jpg"
            img = Image.new('RGB', (10, 10), color='red')
            img.save(img_path)
            paths.append(str(img_path))

            thumb = Image.new('RGB', (5, 5), color='blue')
            cache.put(str(img_path), thumb, (5, 5))

        # Access first item (move to end)
        cache.get(paths[0], (5, 5))

        # Add 4th item (should evict item 1, not item 0)
        img_path = tmp_path / "image3.jpg"
        img = Image.new('RGB', (10, 10), color='red')
        img.save(img_path)
        thumb = Image.new('RGB', (5, 5), color='blue')
        cache.put(str(img_path), thumb, (5, 5))

        # Item 0 should still be cached (was moved to end)
        assert cache.get(paths[0], (5, 5)) is not None

        # Item 1 should be evicted
        assert cache.get(paths[1], (5, 5)) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
