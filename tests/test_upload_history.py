"""
Unit tests for upload_history.py - Session Tracking Module

Tests session management, record tracking, and persistence.
"""

import pytest
import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from modules.upload_history import (
    UploadHistory,
    UploadSession,
    UploadRecord,
    get_upload_history
)


class TestUploadHistory:
    """Test suite for UploadHistory."""

    @pytest.fixture
    def history(self, tmp_path):
        """Create fresh history instance for each test."""
        history_dir = tmp_path / "history"
        return UploadHistory(history_dir)

    def test_start_session_creates_session(self, history):
        """Test that starting a session creates a session object."""
        session_id = history.start_session("imx.to", 10)

        assert history.current_session is not None
        assert history.current_session.session_id == session_id
        assert history.current_session.service == "imx.to"
        assert history.current_session.total_files == 10
        assert history.current_session.status == 'in_progress'

    def test_session_id_format(self, history):
        """Test that session ID follows expected format (YYYYMMDD_HHMMSS)."""
        session_id = history.start_session("pixhost.to", 5)

        # Should be in format YYYYMMDD_HHMMSS
        assert len(session_id) == 15  # 8 digits + underscore + 6 digits
        assert session_id[8] == '_'

        # Should be parseable as timestamp
        datetime.strptime(session_id, "%Y%m%d_%H%M%S")

    def test_add_record_to_session(self, history):
        """Test adding upload records to session."""
        history.start_session("imx.to", 5)

        record = UploadRecord(
            file_path="/path/to/image.jpg",
            service="imx.to",
            image_url="https://example.com/img.jpg",
            thumbnail_url="https://example.com/thumb.jpg",
            gallery_id="ABC123",
            status="success",
            timestamp=datetime.now().isoformat()
        )

        history.add_record(record)

        assert len(history.current_session.records) == 1
        assert history.current_session.successful == 1
        assert history.current_session.failed == 0

    def test_add_failed_record(self, history):
        """Test adding failed upload record."""
        history.start_session("imx.to", 5)

        record = UploadRecord(
            file_path="/path/to/image.jpg",
            service="imx.to",
            image_url=None,
            thumbnail_url=None,
            gallery_id=None,
            status="failed",
            timestamp=datetime.now().isoformat(),
            error_message="Network timeout"
        )

        history.add_record(record)

        assert history.current_session.successful == 0
        assert history.current_session.failed == 1

    def test_end_session_saves_to_disk(self, history):
        """Test that ending session saves to disk."""
        session_id = history.start_session("imx.to", 3)
        history.end_session("completed")

        # Check file exists
        session_file = history.history_dir / f"{session_id}.json"
        assert session_file.exists()

        # Verify content
        with open(session_file, 'r') as f:
            data = json.load(f)

        assert data['session_id'] == session_id
        assert data['service'] == "imx.to"
        assert data['status'] == "completed"
        assert data['total_files'] == 3

    def test_end_session_clears_current(self, history):
        """Test that ending session clears current_session."""
        history.start_session("imx.to", 5)
        assert history.current_session is not None

        history.end_session("completed")
        assert history.current_session is None

    def test_load_session_from_disk(self, history):
        """Test loading a session from disk."""
        # Create and save a session
        session_id = history.start_session("pixhost.to", 5)

        record = UploadRecord(
            file_path="/test.jpg",
            service="pixhost.to",
            image_url="https://test.com/img.jpg",
            thumbnail_url="https://test.com/thumb.jpg",
            gallery_id="XYZ",
            status="success",
            timestamp=datetime.now().isoformat()
        )
        history.add_record(record)
        history.end_session("completed")

        # Load it back
        loaded = history.load_session(session_id)

        assert loaded is not None
        assert loaded.session_id == session_id
        assert loaded.service == "pixhost.to"
        assert loaded.total_files == 5
        assert loaded.status == "completed"
        assert len(loaded.records) == 1

    def test_load_nonexistent_session(self, history):
        """Test loading a session that doesn't exist."""
        result = history.load_session("nonexistent_session")
        assert result is None

    def test_get_failed_files(self, history):
        """Test retrieving failed files from a session."""
        session_id = history.start_session("imx.to", 5)

        # Add successful and failed records
        success_record = UploadRecord(
            file_path="/success.jpg",
            service="imx.to",
            image_url="https://test.com/img.jpg",
            thumbnail_url="https://test.com/thumb.jpg",
            gallery_id="ABC",
            status="success",
            timestamp=datetime.now().isoformat()
        )

        failed_record1 = UploadRecord(
            file_path="/failed1.jpg",
            service="imx.to",
            image_url=None,
            thumbnail_url=None,
            gallery_id=None,
            status="failed",
            timestamp=datetime.now().isoformat(),
            error_message="Timeout"
        )

        failed_record2 = UploadRecord(
            file_path="/failed2.jpg",
            service="imx.to",
            image_url=None,
            thumbnail_url=None,
            gallery_id=None,
            status="failed",
            timestamp=datetime.now().isoformat(),
            error_message="Auth error"
        )

        history.add_record(success_record)
        history.add_record(failed_record1)
        history.add_record(failed_record2)
        history.end_session("completed")

        # Get failed files
        failed_files = history.get_failed_files(session_id)

        assert len(failed_files) == 2
        assert "/failed1.jpg" in failed_files
        assert "/failed2.jpg" in failed_files
        assert "/success.jpg" not in failed_files

    def test_list_sessions(self, history):
        """Test listing recent sessions."""
        # Create multiple sessions
        session_ids = []
        for i in range(5):
            sid = history.start_session(f"service{i}", i+1)
            session_ids.append(sid)
            history.end_session("completed")
            # Sleep to ensure unique session IDs (YYYYMMDD_HHMMSS format)
            time.sleep(1.1)

        # List sessions
        sessions = history.list_sessions(limit=3)

        assert len(sessions) == 3
        # Should be most recent first
        assert sessions[0]['session_id'] == session_ids[-1]

    def test_get_statistics(self, history):
        """Test overall statistics calculation."""
        # Create sessions with varying success/failure
        for i in range(3):
            history.start_session("test_service", 10)
            time.sleep(1.1)  # Ensure unique session IDs

            # Add some successful records
            for j in range(7):
                record = UploadRecord(
                    file_path=f"/file{j}.jpg",
                    service="test_service",
                    image_url="https://test.com/img.jpg",
                    thumbnail_url="https://test.com/thumb.jpg",
                    gallery_id="ABC",
                    status="success",
                    timestamp=datetime.now().isoformat()
                )
                history.add_record(record)

            # Add some failed records
            for j in range(3):
                record = UploadRecord(
                    file_path=f"/fail{j}.jpg",
                    service="test_service",
                    image_url=None,
                    thumbnail_url=None,
                    gallery_id=None,
                    status="failed",
                    timestamp=datetime.now().isoformat()
                )
                history.add_record(record)

            history.end_session("completed")

        # Get statistics
        stats = history.get_statistics()

        assert stats['total_sessions'] == 3
        assert stats['total_files_uploaded'] == 30  # 3 sessions * 10 files
        assert stats['successful_uploads'] == 21  # 3 sessions * 7 success
        assert stats['failed_uploads'] == 9  # 3 sessions * 3 failures
        assert stats['success_rate_percent'] == 70.0

    def test_cleanup_old_sessions(self, history, tmp_path):
        """Test cleanup of old session files."""
        import time

        # Create session and save
        session_id = history.start_session("test", 1)
        history.end_session("completed")

        session_file = history.history_dir / f"{session_id}.json"
        assert session_file.exists()

        # Modify file timestamp to be old
        old_time = time.time() - (31 * 24 * 60 * 60)  # 31 days ago
        os.utime(session_file, (old_time, old_time))

        # Cleanup sessions older than 30 days
        history.cleanup_old_sessions(days=30)

        # File should be deleted
        assert not session_file.exists()

    def test_add_record_without_active_session(self, history):
        """Test that adding record without session is handled gracefully."""
        record = UploadRecord(
            file_path="/test.jpg",
            service="test",
            image_url="https://test.com/img.jpg",
            thumbnail_url="https://test.com/thumb.jpg",
            gallery_id="ABC",
            status="success",
            timestamp=datetime.now().isoformat()
        )

        # Should not crash, just log warning
        history.add_record(record)

        # No current session
        assert history.current_session is None

    def test_multiple_sessions_sequential(self, history):
        """Test creating multiple sessions sequentially."""
        # Session 1
        sid1 = history.start_session("service1", 5)
        history.end_session("completed")

        # Sleep to ensure different session IDs
        time.sleep(1.1)

        # Session 2
        sid2 = history.start_session("service2", 10)
        history.end_session("completed")

        # Both should exist
        assert history.load_session(sid1) is not None
        assert history.load_session(sid2) is not None
        assert sid1 != sid2


class TestUploadHistorySingleton:
    """Test singleton pattern for upload history."""

    def test_get_upload_history_singleton(self):
        """Test that get_upload_history returns singleton."""
        history1 = get_upload_history()
        history2 = get_upload_history()

        assert history1 is history2

    def test_singleton_persists_across_calls(self):
        """Test that singleton state persists."""
        history1 = get_upload_history()
        session_id = history1.start_session("test", 5)

        history2 = get_upload_history()
        assert history2.current_session is not None
        assert history2.current_session.session_id == session_id


class TestUploadRecord:
    """Test UploadRecord dataclass."""

    def test_upload_record_creation(self):
        """Test creating upload record."""
        record = UploadRecord(
            file_path="/test/image.jpg",
            service="imx.to",
            image_url="https://imx.to/i/abc.jpg",
            thumbnail_url="https://imx.to/t/abc.jpg",
            gallery_id="GALLERY123",
            status="success",
            timestamp="2024-01-01T12:00:00"
        )

        assert record.file_path == "/test/image.jpg"
        assert record.service == "imx.to"
        assert record.status == "success"
        assert record.error_message is None

    def test_upload_record_with_error(self):
        """Test creating failed upload record."""
        record = UploadRecord(
            file_path="/test/failed.jpg",
            service="pixhost.to",
            image_url=None,
            thumbnail_url=None,
            gallery_id=None,
            status="failed",
            timestamp="2024-01-01T12:00:00",
            error_message="Network timeout after 3 retries",
            file_size=1024000
        )

        assert record.status == "failed"
        assert record.error_message == "Network timeout after 3 retries"
        assert record.file_size == 1024000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
