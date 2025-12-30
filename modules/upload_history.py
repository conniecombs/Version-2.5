# modules/upload_history.py
"""
Upload History - Track and Resume Uploads

Maintains a persistent record of upload sessions for:
- Resume failed/interrupted uploads
- Track upload statistics
- Audit trail for uploaded files
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class UploadRecord:
    """Record of a single file upload."""
    file_path: str
    service: str
    image_url: Optional[str]
    thumbnail_url: Optional[str]
    gallery_id: Optional[str]
    status: str  # 'success', 'failed', 'pending'
    timestamp: str
    error_message: Optional[str] = None
    file_size: Optional[int] = None


@dataclass
class UploadSession:
    """Record of an upload batch/session."""
    session_id: str
    start_time: str
    end_time: Optional[str]
    service: str
    total_files: int
    successful: int
    failed: int
    status: str  # 'completed', 'failed', 'interrupted'
    records: List[UploadRecord]


class UploadHistory:
    """
    Manages upload history with persistence.

    Features:
    - Persistent storage of upload records
    - Resume interrupted/failed uploads
    - Statistics and audit trail
    - Automatic cleanup of old records
    """

    DEFAULT_HISTORY_DIR = Path.home() / ".connies_uploader" / "history"

    def __init__(self, history_dir: Optional[Path] = None):
        """
        Initialize upload history manager.

        Args:
            history_dir: Directory for history files (default: ~/.connies_uploader/history)
        """
        self.history_dir = history_dir or self.DEFAULT_HISTORY_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[UploadSession] = None

    def start_session(self, service: str, total_files: int) -> str:
        """
        Start a new upload session.

        Args:
            service: Upload service name
            total_files: Total number of files to upload

        Returns:
            Session ID
        """
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.current_session = UploadSession(
            session_id=session_id,
            start_time=datetime.now().isoformat(),
            end_time=None,
            service=service,
            total_files=total_files,
            successful=0,
            failed=0,
            status='in_progress',
            records=[]
        )

        logger.info(f"Started upload session: {session_id} ({total_files} files)")
        return session_id

    def add_record(self, record: UploadRecord):
        """
        Add an upload record to the current session.

        Args:
            record: Upload record to add
        """
        if not self.current_session:
            logger.warning("No active session - cannot add record")
            return

        self.current_session.records.append(record)

        if record.status == 'success':
            self.current_session.successful += 1
        elif record.status == 'failed':
            self.current_session.failed += 1

    def end_session(self, status: str = 'completed'):
        """
        End the current upload session and save to disk.

        Args:
            status: Final session status ('completed', 'failed', 'interrupted')
        """
        if not self.current_session:
            logger.warning("No active session to end")
            return

        self.current_session.end_time = datetime.now().isoformat()
        self.current_session.status = status

        # Save to disk
        self._save_session(self.current_session)

        logger.info(
            f"Ended upload session: {self.current_session.session_id} "
            f"({self.current_session.successful}/{self.current_session.total_files} successful)"
        )

        self.current_session = None

    def _save_session(self, session: UploadSession):
        """Save session to disk as JSON."""
        try:
            session_file = self.history_dir / f"{session.session_id}.json"

            session_data = {
                'session_id': session.session_id,
                'start_time': session.start_time,
                'end_time': session.end_time,
                'service': session.service,
                'total_files': session.total_files,
                'successful': session.successful,
                'failed': session.failed,
                'status': session.status,
                'records': [asdict(r) for r in session.records]
            }

            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)

            logger.debug(f"Saved upload session to: {session_file}")

        except Exception as e:
            logger.error(f"Failed to save upload session: {e}")

    def load_session(self, session_id: str) -> Optional[UploadSession]:
        """
        Load a session from disk.

        Args:
            session_id: Session ID to load

        Returns:
            UploadSession if found, None otherwise
        """
        try:
            session_file = self.history_dir / f"{session_id}.json"

            if not session_file.exists():
                return None

            with open(session_file, 'r') as f:
                data = json.load(f)

            # Reconstruct records
            records = [UploadRecord(**r) for r in data['records']]

            session = UploadSession(
                session_id=data['session_id'],
                start_time=data['start_time'],
                end_time=data.get('end_time'),
                service=data['service'],
                total_files=data['total_files'],
                successful=data['successful'],
                failed=data['failed'],
                status=data['status'],
                records=records
            )

            return session

        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def get_failed_files(self, session_id: str) -> List[str]:
        """
        Get list of failed files from a session.

        Args:
            session_id: Session ID

        Returns:
            List of file paths that failed to upload
        """
        session = self.load_session(session_id)
        if not session:
            return []

        return [r.file_path for r in session.records if r.status == 'failed']

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List recent upload sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session summaries (most recent first)
        """
        try:
            session_files = sorted(
                self.history_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )

            sessions = []
            for session_file in session_files[:limit]:
                try:
                    with open(session_file, 'r') as f:
                        data = json.load(f)

                    # Summary only (no full records)
                    sessions.append({
                        'session_id': data['session_id'],
                        'start_time': data['start_time'],
                        'service': data['service'],
                        'total_files': data['total_files'],
                        'successful': data['successful'],
                        'failed': data['failed'],
                        'status': data['status']
                    })
                except Exception as e:
                    logger.warning(f"Failed to load session file {session_file}: {e}")
                    continue

            return sessions

        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get overall upload statistics.

        Returns:
            Dictionary with statistics
        """
        sessions = self.list_sessions(limit=100)  # Last 100 sessions

        total_sessions = len(sessions)
        total_files = sum(s['total_files'] for s in sessions)
        total_successful = sum(s['successful'] for s in sessions)
        total_failed = sum(s['failed'] for s in sessions)

        success_rate = (total_successful / total_files * 100) if total_files > 0 else 0

        return {
            'total_sessions': total_sessions,
            'total_files_uploaded': total_files,
            'successful_uploads': total_successful,
            'failed_uploads': total_failed,
            'success_rate_percent': round(success_rate, 2)
        }

    def cleanup_old_sessions(self, days: int = 30):
        """
        Delete session files older than specified days.

        Args:
            days: Delete sessions older than this many days
        """
        try:
            import time
            cutoff_time = time.time() - (days * 24 * 60 * 60)

            deleted = 0
            for session_file in self.history_dir.glob("*.json"):
                if session_file.stat().st_mtime < cutoff_time:
                    session_file.unlink()
                    deleted += 1

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old session files (older than {days} days)")

        except Exception as e:
            logger.error(f"Failed to cleanup old sessions: {e}")


# Global singleton
_upload_history: Optional[UploadHistory] = None


def get_upload_history() -> UploadHistory:
    """Get the global upload history instance."""
    global _upload_history
    if _upload_history is None:
        _upload_history = UploadHistory()
    return _upload_history
