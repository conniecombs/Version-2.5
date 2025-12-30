# modules/app_state.py
"""
Application state management using dataclasses.
Consolidates scattered instance variables into organized, typed structures.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import threading
import queue


@dataclass
class UploadState:
    """State related to upload operations"""
    upload_total: int = 0
    upload_count: int = 0
    is_uploading: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def reset(self):
        """Reset upload state for new batch"""
        self.upload_total = 0
        self.upload_count = 0
        self.is_uploading = False
        self.cancel_event.clear()

    def increment_count(self):
        """Safely increment upload count"""
        self.upload_count += 1

    def is_complete(self) -> bool:
        """Check if upload batch is complete"""
        return self.upload_count >= self.upload_total


@dataclass
class FileManagementState:
    """State for file and group management"""
    file_widgets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    groups: List[Any] = field(default_factory=list)
    image_refs: List[Any] = field(default_factory=list)

    def clear_all(self):
        """Clear all file management state"""
        self.file_widgets.clear()
        self.groups.clear()
        self.image_refs.clear()

    def get_pending_files(self) -> Dict[Any, List[str]]:
        """Get files grouped by their group that are pending upload"""
        pending_by_group = {}
        for group in self.groups:
            for fp in group.files:
                if fp in self.file_widgets and self.file_widgets[fp]['state'] == 'pending':
                    if group not in pending_by_group:
                        pending_by_group[group] = []
                    pending_by_group[group].append(fp)
        return pending_by_group


@dataclass
class ResultsState:
    """State for upload results and output"""
    results: List[tuple] = field(default_factory=list)
    current_output_files: List[str] = field(default_factory=list)
    clipboard_buffer: List[str] = field(default_factory=list)
    pix_galleries_to_finalize: List[Dict] = field(default_factory=list)

    def clear_results(self):
        """Clear results after processing"""
        self.results.clear()
        self.pix_galleries_to_finalize.clear()

    def add_output_file(self, filepath: str):
        """Add an output file to the list"""
        self.current_output_files.append(filepath)

    def add_to_clipboard_buffer(self, text: str):
        """Add text to clipboard buffer"""
        self.clipboard_buffer.append(text)

    def get_clipboard_text(self) -> str:
        """Get all buffered clipboard text"""
        return "\n\n".join(self.clipboard_buffer)


@dataclass
class ServiceAuthState:
    """State for service authentication"""
    turbo_cookies: Optional[Any] = None
    turbo_endpoint: Optional[str] = None
    turbo_upload_id: Optional[str] = None
    vipr_session: Optional[Any] = None
    vipr_meta: Optional[Dict] = None
    vipr_galleries_map: Dict[str, str] = field(default_factory=dict)

    def clear_turbo(self):
        """Clear Turbo service state"""
        self.turbo_cookies = None
        self.turbo_endpoint = None
        self.turbo_upload_id = None

    def clear_vipr(self):
        """Clear Vipr service state"""
        self.vipr_session = None
        self.vipr_meta = None
        self.vipr_galleries_map.clear()


@dataclass
class QueueState:
    """State for inter-thread communication queues"""
    progress_queue: queue.Queue = field(default_factory=queue.Queue)
    ui_queue: queue.Queue = field(default_factory=queue.Queue)
    result_queue: queue.Queue = field(default_factory=queue.Queue)

    def clear_all(self):
        """Clear all queues"""
        # Empty the queues
        while not self.progress_queue.empty():
            try:
                self.progress_queue.get_nowait()
            except queue.Empty:
                break

        while not self.ui_queue.empty():
            try:
                self.ui_queue.get_nowait()
            except queue.Empty:
                break

        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break


@dataclass
class UIState:
    """State for UI-related variables"""
    log_cache: List[str] = field(default_factory=list)
    log_window_ref: Optional[Any] = None

    def add_log(self, message: str):
        """Add a log message"""
        self.log_cache.append(message)


@dataclass
class AppState:
    """
    Central application state container.

    Consolidates all application state into organized, typed structures.
    This makes state management clearer and enables easier testing.
    """
    upload: UploadState = field(default_factory=UploadState)
    files: FileManagementState = field(default_factory=FileManagementState)
    results: ResultsState = field(default_factory=ResultsState)
    auth: ServiceAuthState = field(default_factory=ServiceAuthState)
    queues: QueueState = field(default_factory=QueueState)
    ui: UIState = field(default_factory=UIState)

    # Thread safety
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset_for_new_session(self):
        """Reset state for a completely new session"""
        self.upload.reset()
        self.files.clear_all()
        self.results = ResultsState()  # Create fresh results state
        self.queues.clear_all()

    def reset_for_new_upload(self):
        """Reset state for a new upload batch (keeps files)"""
        self.upload.reset()
        self.results.clear_results()
        self.queues.clear_all()

    def get_stats(self) -> Dict[str, Any]:
        """Get current state statistics for debugging/monitoring"""
        return {
            'upload_progress': f"{self.upload.upload_count}/{self.upload.upload_total}",
            'is_uploading': self.upload.is_uploading,
            'total_files': len(self.files.file_widgets),
            'total_groups': len(self.files.groups),
            'pending_results': len(self.results.results),
            'output_files': len(self.results.current_output_files),
            'queues': {
                'progress': self.queues.progress_queue.qsize(),
                'ui': self.queues.ui_queue.qsize(),
                'result': self.queues.result_queue.qsize()
            }
        }

    def __str__(self) -> str:
        """String representation for debugging"""
        stats = self.get_stats()
        return f"AppState({stats})"


class StateManager:
    """
    Manages application state with thread-safe operations.

    Provides a facade over AppState for common operations.
    """

    def __init__(self, state: Optional[AppState] = None):
        self.state = state or AppState()

    def with_lock(self, operation):
        """Execute operation with state lock"""
        with self.state.lock:
            return operation()

    def increment_upload_count(self):
        """Thread-safe upload count increment"""
        with self.state.lock:
            self.state.upload.increment_count()

    def is_upload_complete(self) -> bool:
        """Thread-safe check if upload is complete"""
        with self.state.lock:
            return self.state.upload.is_complete()

    def get_pending_files(self) -> Dict[Any, List[str]]:
        """Get pending files for upload"""
        with self.state.lock:
            return self.state.files.get_pending_files()

    def add_result(self, filepath: str, image_url: str, thumb_url: str):
        """Thread-safe result addition"""
        with self.state.lock:
            self.state.results.results.append((filepath, image_url, thumb_url))

    def snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of current state for debugging"""
        with self.state.lock:
            return self.state.get_stats()
