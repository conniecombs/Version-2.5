# Future Improvements Roadmap
## Connie's Uploader Ultimate - Post v2.5

This document tracks potential improvements for future pull requests beyond v2.5. Each improvement is scoped as an independent PR to maintain focused, reviewable changes.

---

## 1. Integration Tests with Mock Uploads

### Overview
Implement end-to-end integration tests that simulate the complete upload workflow using mocked HTTP responses for each service.

### Rationale
- **Current State**: Unit tests cover individual modules (config, cache, history, path validation) with 75-92% coverage
- **Gap**: No tests validate the complete upload pipeline from file selection → API call → result processing
- **Benefit**: Catch regression bugs in service integrations, upload coordinator logic, and error handling workflows

### Implementation Approach

#### Test Structure
```python
# tests/integration/test_upload_workflow.py
import pytest
from unittest.mock import Mock, patch
import httpx

class TestUploadWorkflow:
    """End-to-end upload workflow tests"""

    @pytest.fixture
    def mock_http_responses(self):
        """Fixture providing mock responses for each service"""
        return {
            'imx': httpx.Response(200, json={'data': {'image': 'https://i.imx.to/test.jpg'}}),
            'pixhost': httpx.Response(200, text='<img src="https://img.pixhost.to/test.jpg">'),
            'turbo': httpx.Response(200, text='https://www.turboimagehost.com/p/12345/test.jpg'),
            'vipr': httpx.Response(200, json={'url': 'https://vipr.im/test.jpg'})
        }

    @patch('httpx.Client.post')
    def test_imx_upload_end_to_end(self, mock_post, mock_http_responses, tmp_path):
        """Test complete IMX upload workflow"""
        # Setup
        test_image = tmp_path / "test.jpg"
        test_image.write_bytes(b'\x89PNG...')  # Minimal PNG

        mock_post.return_value = mock_http_responses['imx']

        # Execute upload workflow
        from modules.upload_coordinator import UploadCoordinator
        coordinator = UploadCoordinator(...)

        result = coordinator.upload_files(
            files=[str(test_image)],
            service='imx.to',
            api_key='test_key'
        )

        # Assertions
        assert result.success_count == 1
        assert result.failed_count == 0
        assert 'https://i.imx.to/test.jpg' in result.urls
        mock_post.assert_called_once()

    def test_retry_on_network_failure(self, tmp_path):
        """Test upload retry logic on transient failures"""
        # Simulate: Fail → Fail → Success
        with patch('httpx.Client.post') as mock_post:
            mock_post.side_effect = [
                httpx.TimeoutException("Connection timeout"),
                httpx.TimeoutException("Connection timeout"),
                httpx.Response(200, json={'data': {'image': 'https://i.imx.to/test.jpg'}})
            ]

            # Should succeed after 2 retries
            result = coordinator.upload_files(...)
            assert result.success_count == 1
            assert mock_post.call_count == 3

    def test_gallery_creation_workflow(self):
        """Test multi-file upload with auto-gallery creation"""
        # Test pixhost gallery creation flow
        pass
```

#### Services to Mock
1. **IMX.to**: API endpoint with JSON responses
2. **Pixhost**: HTML scraping for URLs, gallery creation
3. **TurboImageHost**: Dynamic endpoint resolution, HTML parsing
4. **Vipr.im**: Login flow, JSON API, gallery management

#### Test Coverage Areas
- ✅ Successful uploads for all services
- ✅ Network failure handling (timeouts, connection errors)
- ✅ Retry logic with exponential backoff
- ✅ Credential validation before upload
- ✅ Gallery creation and linking
- ✅ Progress tracking throughout pipeline
- ✅ Result queue processing
- ✅ Upload cancellation mid-workflow

### Dependencies
- **pytest-httpx**: For mocking httpx requests
- **pytest-mock**: For patching modules
- **respx**: Alternative HTTP mocking library

### Effort Estimate
- **Complexity**: Medium
- **Time**: 2-3 days
- **Files Affected**: `tests/integration/` (new), possibly `conftest.py`

### Success Criteria
- ✅ 80%+ integration test coverage for upload workflows
- ✅ All four services have end-to-end test coverage
- ✅ Tests run in CI/CD pipeline in <30 seconds
- ✅ No actual HTTP requests made during tests (all mocked)

---

## 2. GUI Unit Tests (Requires Headless Testing Framework)

### Overview
Implement automated testing for GUI components using a headless testing framework to validate UI behavior, widget creation, and user interactions.

### Rationale
- **Current State**: Zero GUI test coverage; manual testing required for all UI changes
- **Gap**: Cannot verify UI regressions, widget state updates, or user interaction flows
- **Benefit**: Catch UI bugs before deployment, enable refactoring with confidence

### Implementation Approach

#### Framework Selection
**Recommended**: `pytest` + `pytest-qt` (for Qt/Tk testing) or `unittest` + `tkinter` virtual display

```python
# tests/gui/test_main_window.py
import pytest
import tkinter as tk
from unittest.mock import Mock, patch

# Use xvfb for headless testing on CI/CD
@pytest.fixture
def app():
    """Fixture providing app instance with virtual display"""
    from main import UploaderApp

    root = tk.Tk()
    app = UploaderApp(root)

    yield app

    root.destroy()

class TestMainWindow:
    def test_window_creation(self, app):
        """Test main window initializes correctly"""
        assert app.winfo_exists()
        assert app.title() == "Connie's Uploader Ultimate v2.5"

    def test_add_files_button_exists(self, app):
        """Test Add Files button is present and clickable"""
        add_btn = app.nametowidget('add_files_btn')
        assert add_btn.winfo_exists()
        assert add_btn['state'] != 'disabled'

    def test_drag_drop_file_addition(self, app):
        """Test drag-and-drop adds files to list"""
        initial_count = len(app.file_widgets)

        # Simulate drag-and-drop event
        app._on_drop(['/fake/path/image1.jpg', '/fake/path/image2.jpg'])

        assert len(app.file_widgets) == initial_count + 2

    def test_service_selection_updates_ui(self, app):
        """Test selecting service updates credential fields"""
        app.service_var.set('pixhost.to')
        app.update()  # Process UI events

        # Pixhost should show content ID field
        assert app.pixhost_content_frame.winfo_viewable()

        app.service_var.set('imx.to')
        app.update()

        # IMX should show API key field
        assert app.api_key_entry.winfo_viewable()

    def test_upload_button_disabled_when_no_files(self, app):
        """Test upload button is disabled with empty file list"""
        app.clear_list()
        assert app.upload_btn['state'] == 'disabled'

    def test_progress_bar_updates(self, app):
        """Test progress bar reflects upload progress"""
        app._update_progress(5, 10)  # 50% progress
        assert app.progress_bar.get() == 0.5

    @patch('modules.upload_coordinator.UploadCoordinator.start_upload')
    def test_start_upload_button_triggers_workflow(self, mock_upload, app):
        """Test clicking upload button initiates upload"""
        # Add mock files
        app.file_widgets = {'/fake/file.jpg': Mock()}
        app.service_var.set('imx.to')

        app.start_upload()

        mock_upload.assert_called_once()

    def test_cancel_button_stops_upload(self, app):
        """Test cancel button sets cancellation flag"""
        app.is_uploading = True
        app.cancel_upload()

        assert app.cancel_event.is_set()
        assert not app.is_uploading
```

#### GUI Components to Test
1. **Main Window**: Initialization, widget creation, layout
2. **File List**: Add/remove files, group collapsing, drag-and-drop
3. **Service Selection**: Dropdown updates, credential field visibility
4. **Upload Controls**: Button states, progress tracking, cancellation
5. **Results Panel**: URL display, copy functionality, preview loading
6. **Settings Dialog**: Configuration updates, template management
7. **Execution Log**: Filtering, export functionality

#### Headless Environment Setup
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y xvfb python3-tk python3-pil python3-pil.imagetk

    - name: Install Python dependencies
      run: pip install -r requirements.txt

    - name: Run headless GUI tests
      run: xvfb-run pytest tests/gui/ -v
```

### Dependencies
- **xvfb** (X Virtual Framebuffer): Headless display server for Linux CI/CD
- **pytest-xvfb**: Pytest plugin for automatic xvfb management
- **pillow**: Already installed for image handling

### Effort Estimate
- **Complexity**: High (GUI testing is inherently complex)
- **Time**: 4-5 days
- **Files Affected**: `tests/gui/` (new), `.github/workflows/test.yml`

### Success Criteria
- ✅ 60%+ coverage of main GUI components
- ✅ Tests pass in headless CI/CD environment
- ✅ Widget state changes are validated
- ✅ User interaction flows are tested
- ✅ Tests run in <60 seconds

### Challenges
- **CustomTkinter Compatibility**: May require special handling vs standard Tkinter
- **Asynchronous UI Updates**: Need to handle queued UI updates properly
- **Platform Differences**: Windows/Mac/Linux rendering variations

---

## 3. Automated Performance Benchmarking

### Overview
Implement automated benchmarks to track performance metrics across versions, detecting regressions in upload speed, memory usage, and thumbnail generation.

### Rationale
- **Current State**: Manual performance testing; v2.5 claims "20-40% faster uploads" without automated validation
- **Gap**: No systematic way to measure performance improvements or catch regressions
- **Benefit**: Data-driven optimization decisions, prevent performance degradation

### Implementation Approach

#### Benchmark Suite Structure
```python
# tests/benchmarks/test_performance.py
import pytest
import time
import psutil
from pathlib import Path

class TestPerformanceBenchmarks:
    """Performance benchmarks with regression detection"""

    @pytest.fixture
    def sample_images(self, tmp_path):
        """Generate test images of various sizes"""
        from PIL import Image

        images = []
        for size in [(100, 100), (1000, 1000), (3000, 3000)]:
            img_path = tmp_path / f"test_{size[0]}x{size[1]}.jpg"
            img = Image.new('RGB', size, color='red')
            img.save(img_path, 'JPEG')
            images.append(img_path)

        return images

    @pytest.mark.benchmark(group="thumbnail-cache")
    def test_thumbnail_generation_speed(self, benchmark, sample_images):
        """Benchmark thumbnail generation with caching"""
        from modules.thumbnail_cache import ThumbnailCache

        cache = ThumbnailCache(cache_dir=None)  # Memory-only

        def generate_thumbnails():
            for img_path in sample_images * 10:  # 30 images
                cache.get_thumbnail(str(img_path), size=(40, 40))

        result = benchmark(generate_thumbnails)

        # Assertions: Should complete in <500ms for 30 images
        assert result.stats.mean < 0.5

    @pytest.mark.benchmark(group="thumbnail-cache")
    def test_cache_hit_performance(self, benchmark, sample_images):
        """Benchmark cache hit rate and speed"""
        from modules.thumbnail_cache import ThumbnailCache

        cache = ThumbnailCache(cache_dir=None)

        # Warm up cache
        for img in sample_images:
            cache.get_thumbnail(str(img), size=(40, 40))

        def access_cached_thumbnails():
            for img in sample_images * 100:  # 300 accesses
                cache.get_thumbnail(str(img), size=(40, 40))

        result = benchmark(access_cached_thumbnails)

        # Cache hits should be <1ms average
        assert result.stats.mean < 0.001

    @pytest.mark.benchmark(group="upload-workflow")
    def test_upload_coordinator_overhead(self, benchmark, sample_images):
        """Benchmark upload coordination logic (excluding actual upload)"""
        from modules.upload_coordinator import UploadCoordinator
        from unittest.mock import Mock

        coordinator = UploadCoordinator(
            progress_queue=Mock(),
            result_queue=Mock(),
            cancel_event=Mock()
        )

        def prepare_upload():
            coordinator.prepare_upload(
                files=[str(img) for img in sample_images],
                service='imx.to',
                credentials={'api_key': 'test'}
            )

        result = benchmark(prepare_upload)

        # Preparation should be fast (<100ms for 30 files)
        assert result.stats.mean < 0.1

    def test_memory_usage_large_batch(self, sample_images, tmp_path):
        """Test memory usage with 1000+ file batch"""
        import gc
        from modules.thumbnail_cache import ThumbnailCache

        # Generate 1000 test images
        images = []
        for i in range(1000):
            img_path = tmp_path / f"img_{i}.jpg"
            img_path.write_bytes(sample_images[0].read_bytes())
            images.append(img_path)

        # Measure memory before
        gc.collect()
        process = psutil.Process()
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        # Load all thumbnails
        cache = ThumbnailCache(cache_dir=None)
        for img in images:
            cache.get_thumbnail(str(img), size=(40, 40))

        # Measure memory after
        gc.collect()
        mem_after = process.memory_info().rss / 1024 / 1024  # MB

        memory_increase = mem_after - mem_before

        # Should not exceed 200MB for 1000 thumbnails
        assert memory_increase < 200, f"Memory increase: {memory_increase:.2f} MB"

    @pytest.mark.benchmark(group="config-loading")
    def test_config_load_performance(self, benchmark, tmp_path):
        """Benchmark YAML config loading speed"""
        from modules.config_loader import ConfigLoader

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
network:
  timeout_seconds: 60.0
  retry_count: 3
threading:
  imx_threads: 5
  pixhost_threads: 3
""")

        def load_config():
            return ConfigLoader(str(config_file)).load()

        result = benchmark(load_config)

        # Config loading should be <10ms
        assert result.stats.mean < 0.01
```

#### Benchmark Metrics to Track
1. **Thumbnail Generation**
   - Cold cache: Time to generate N thumbnails
   - Warm cache: Cache hit rate and retrieval speed
   - Memory usage for large batches

2. **Upload Workflow**
   - Upload coordinator initialization time
   - File validation overhead
   - Progress tracking latency

3. **Configuration**
   - Config file loading time
   - Config validation time

4. **UI Performance**
   - File list rendering time (100, 500, 1000 files)
   - Progress bar update frequency
   - UI queue processing speed

#### Automated Regression Detection
```python
# tests/benchmarks/conftest.py
import pytest
import json
from pathlib import Path

@pytest.fixture(scope='session')
def benchmark_baseline():
    """Load baseline performance metrics"""
    baseline_file = Path('tests/benchmarks/baseline.json')

    if baseline_file.exists():
        return json.loads(baseline_file.read_text())

    return {}

def pytest_benchmark_compare(config, benchmarks, baseline):
    """Compare current benchmarks to baseline"""
    for bench in benchmarks:
        baseline_value = baseline.get(bench.name, {}).get('mean', 0)

        if baseline_value > 0:
            regression = (bench.stats.mean - baseline_value) / baseline_value

            # Fail if >20% regression
            if regression > 0.2:
                raise AssertionError(
                    f"{bench.name} regressed by {regression*100:.1f}%: "
                    f"{baseline_value:.4f}s → {bench.stats.mean:.4f}s"
                )
```

### Dependencies
- **pytest-benchmark**: Performance benchmarking framework
- **psutil**: Memory and CPU usage monitoring
- **memory_profiler**: Detailed memory profiling (optional)

### Effort Estimate
- **Complexity**: Medium-High
- **Time**: 3-4 days
- **Files Affected**: `tests/benchmarks/` (new), `.github/workflows/benchmark.yml`

### Success Criteria
- ✅ Benchmarks for all critical paths (thumbnails, uploads, config)
- ✅ Automated regression detection (>20% slowdown = fail)
- ✅ Benchmark results tracked over time
- ✅ Memory usage profiling for large batches
- ✅ CI/CD integration with performance reports

### Implementation Steps
1. Install pytest-benchmark and configure
2. Write benchmark tests for critical paths
3. Establish baseline metrics from v2.5
4. Configure CI/CD to run benchmarks on PRs
5. Generate performance comparison reports

---

## 4. Upload Resume After Failure

### Overview
Implement upload session persistence and resume functionality, allowing users to continue failed uploads from the point of failure rather than starting over.

### Rationale
- **Current State**: Failed uploads must be retried manually; large batches risk losing all progress
- **Gap**: No session recovery mechanism; transient network issues waste hours of upload time
- **Benefit**: Massive UX improvement for large batches (100+ files), resilience against network instability

### Implementation Approach

#### Session State Persistence
```python
# modules/upload_session.py
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pathlib import Path
import json
from datetime import datetime

@dataclass
class UploadRecord:
    """Individual file upload record"""
    file_path: str
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    image_url: Optional[str] = None
    thumb_url: Optional[str] = None
    error_message: Optional[str] = None
    upload_timestamp: Optional[str] = None
    retry_count: int = 0

@dataclass
class UploadSession:
    """Persistent upload session state"""
    session_id: str
    service: str
    total_files: int
    created_at: str
    updated_at: str
    status: str  # 'in_progress', 'completed', 'failed', 'paused'

    records: List[UploadRecord] = field(default_factory=list)
    credentials_hash: Optional[str] = None  # For validation
    config: Dict = field(default_factory=dict)

    def save(self, session_dir: Path):
        """Persist session to disk"""
        session_file = session_dir / f"{self.session_id}.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)

        self.updated_at = datetime.now().isoformat()

        session_file.write_text(
            json.dumps(asdict(self), indent=2)
        )

    @classmethod
    def load(cls, session_file: Path) -> 'UploadSession':
        """Load session from disk"""
        data = json.loads(session_file.read_text())

        # Reconstruct records
        records = [UploadRecord(**r) for r in data.pop('records', [])]

        return cls(**data, records=records)

    def get_resumable_files(self) -> List[UploadRecord]:
        """Get files that can be resumed (pending or failed)"""
        return [
            r for r in self.records
            if r.status in ('pending', 'failed') and r.retry_count < 3
        ]

    def mark_completed(self, file_path: str, image_url: str, thumb_url: str):
        """Mark file as successfully uploaded"""
        for record in self.records:
            if record.file_path == file_path:
                record.status = 'completed'
                record.image_url = image_url
                record.thumb_url = thumb_url
                record.upload_timestamp = datetime.now().isoformat()
                break

    def mark_failed(self, file_path: str, error: str):
        """Mark file as failed with error message"""
        for record in self.records:
            if record.file_path == file_path:
                record.status = 'failed'
                record.error_message = error
                record.retry_count += 1
                break

    def get_progress(self) -> Dict:
        """Calculate upload progress"""
        completed = sum(1 for r in self.records if r.status == 'completed')
        failed = sum(1 for r in self.records if r.status == 'failed')
        pending = sum(1 for r in self.records if r.status == 'pending')

        return {
            'completed': completed,
            'failed': failed,
            'pending': pending,
            'progress_pct': (completed / self.total_files) * 100 if self.total_files > 0 else 0
        }
```

#### Resume UI Integration
```python
# modules/upload_coordinator.py (modified)
class UploadCoordinator:
    def __init__(self, ...):
        self.session_dir = Path.home() / '.connies_uploader' / 'sessions'
        self.current_session: Optional[UploadSession] = None

    def start_upload(self, files: List[str], service: str, credentials: Dict, config: Dict):
        """Start new upload or resume existing session"""
        # Check for resumable session
        existing_session = self._find_resumable_session(service, credentials)

        if existing_session:
            # Prompt user to resume
            resume = self._prompt_resume(existing_session)

            if resume:
                return self._resume_upload(existing_session)

        # Start fresh upload
        return self._start_new_upload(files, service, credentials, config)

    def _find_resumable_session(self, service: str, credentials: Dict) -> Optional[UploadSession]:
        """Find incomplete session for this service"""
        cred_hash = self._hash_credentials(credentials)

        for session_file in self.session_dir.glob('*.json'):
            try:
                session = UploadSession.load(session_file)

                if (session.service == service and
                    session.status == 'in_progress' and
                    session.credentials_hash == cred_hash):

                    resumable_files = session.get_resumable_files()
                    if resumable_files:
                        return session
            except Exception as e:
                logger.warning(f"Failed to load session {session_file}: {e}")

        return None

    def _resume_upload(self, session: UploadSession):
        """Resume incomplete upload session"""
        resumable_files = session.get_resumable_files()

        logger.info(
            f"Resuming session {session.session_id}: "
            f"{len(resumable_files)} files remaining"
        )

        # Update session status
        session.status = 'in_progress'
        session.save(self.session_dir)

        # Upload only remaining files
        for record in resumable_files:
            record.status = 'in_progress'
            session.save(self.session_dir)

            try:
                result = self._upload_file(record.file_path, session.config)
                session.mark_completed(record.file_path, result['image_url'], result['thumb_url'])
            except Exception as e:
                session.mark_failed(record.file_path, str(e))

            session.save(self.session_dir)

        # Mark session complete
        session.status = 'completed'
        session.save(self.session_dir)

    def _start_new_upload(self, files: List[str], service: str, credentials: Dict, config: Dict):
        """Start fresh upload with session tracking"""
        session = UploadSession(
            session_id=datetime.now().strftime('%Y%m%d_%H%M%S'),
            service=service,
            total_files=len(files),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            status='in_progress',
            records=[
                UploadRecord(file_path=f, status='pending')
                for f in files
            ],
            credentials_hash=self._hash_credentials(credentials),
            config=config
        )

        session.save(self.session_dir)
        self.current_session = session

        # Upload files with session tracking
        # (Same logic as _resume_upload)
```

#### Resume Prompt Dialog
```python
# UI dialog for resume confirmation
class ResumeUploadDialog(ctk.CTkToplevel):
    """Dialog prompting user to resume incomplete upload"""

    def __init__(self, parent, session: UploadSession):
        super().__init__(parent)

        self.title("Resume Upload?")
        self.geometry("400x250")
        self.transient(parent)
        self.grab_set()

        progress = session.get_progress()

        # Info display
        info_text = f"""
Found incomplete upload session:

Service: {session.service}
Started: {session.created_at}

Progress:
  ✓ Completed: {progress['completed']} files
  ✗ Failed: {progress['failed']} files
  ⧗ Remaining: {progress['pending']} files

Would you like to resume this upload?
"""

        label = ctk.CTkLabel(self, text=info_text, justify='left')
        label.pack(pady=20, padx=20)

        # Buttons
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(pady=10)

        self.result = None

        resume_btn = ctk.CTkButton(
            btn_frame,
            text="Resume",
            command=lambda: self._close(True)
        )
        resume_btn.pack(side='left', padx=5)

        restart_btn = ctk.CTkButton(
            btn_frame,
            text="Start Fresh",
            command=lambda: self._close(False)
        )
        restart_btn.pack(side='left', padx=5)

    def _close(self, resume: bool):
        self.result = resume
        self.destroy()
```

### Features
1. **Automatic Session Persistence**: Every upload tracked in JSON file
2. **Resume on Startup**: Detect incomplete sessions on app launch
3. **Retry Failed Files**: Re-attempt failed uploads up to 3 times
4. **Progress Preservation**: Never lose completed upload URLs
5. **Session Cleanup**: Auto-delete completed sessions after 30 days

### Dependencies
- No new dependencies (uses stdlib JSON)

### Effort Estimate
- **Complexity**: Medium-High
- **Time**: 4-5 days
- **Files Affected**:
  - `modules/upload_session.py` (new)
  - `modules/upload_coordinator.py` (modified)
  - `main.py` (add resume dialog)

### Success Criteria
- ✅ Sessions automatically saved during upload
- ✅ Resume dialog shown on app launch if incomplete session exists
- ✅ Failed files can be retried individually
- ✅ No data loss on app crash or network failure
- ✅ Session files cleaned up after 30 days

---

## 5. Multi-Language Support (i18n/l10n)

### Overview
Implement internationalization (i18n) and localization (l10n) to support multiple languages in the UI, making the application accessible to non-English users.

### Rationale
- **Current State**: All UI text hardcoded in English
- **Gap**: Excludes non-English speaking users
- **Benefit**: Expand user base, improve accessibility, professional polish

### Implementation Approach

#### Translation Framework
**Recommended**: `gettext` (Python standard library) or `babel` (more features)

```python
# modules/i18n.py
import gettext
from pathlib import Path
from typing import Optional

class I18nManager:
    """Internationalization manager"""

    def __init__(self, locale_dir: Path, default_language='en'):
        self.locale_dir = locale_dir
        self.current_language = default_language
        self._translator = None

        self.set_language(default_language)

    def set_language(self, language_code: str):
        """Set active language"""
        locale_path = self.locale_dir / language_code / 'LC_MESSAGES'

        try:
            self._translator = gettext.translation(
                'connies_uploader',
                localedir=self.locale_dir,
                languages=[language_code],
                fallback=True
            )
            self.current_language = language_code
        except Exception as e:
            logger.warning(f"Failed to load language {language_code}: {e}")
            # Fallback to English
            self._translator = gettext.NullTranslations()

    def translate(self, text: str) -> str:
        """Translate text to current language"""
        return self._translator.gettext(text)

    def translate_plural(self, singular: str, plural: str, n: int) -> str:
        """Translate with plural forms"""
        return self._translator.ngettext(singular, plural, n)

# Global translator instance
_i18n = None

def init_i18n(locale_dir: Path, language: str = 'en'):
    """Initialize i18n system"""
    global _i18n
    _i18n = I18nManager(locale_dir, language)

def _(text: str) -> str:
    """Translation shortcut function"""
    if _i18n:
        return _i18n.translate(text)
    return text
```

#### UI Text Extraction
```python
# Before (hardcoded):
add_files_btn = ctk.CTkButton(self, text="Add Files", command=self.add_files)
upload_btn = ctk.CTkButton(self, text="Start Upload", command=self.start_upload)

# After (translatable):
from modules.i18n import _

add_files_btn = ctk.CTkButton(self, text=_("Add Files"), command=self.add_files)
upload_btn = ctk.CTkButton(self, text=_("Start Upload"), command=self.start_upload)
```

#### Translation Files Structure
```
locales/
├── en/
│   └── LC_MESSAGES/
│       ├── connies_uploader.po  # English source
│       └── connies_uploader.mo  # Compiled binary
├── es/
│   └── LC_MESSAGES/
│       ├── connies_uploader.po  # Spanish translation
│       └── connies_uploader.mo
├── fr/
│   └── LC_MESSAGES/
│       └── ...
├── de/
│   └── LC_MESSAGES/
│       └── ...
└── zh_CN/
    └── LC_MESSAGES/
        └── ...
```

#### Example Translation File
```po
# locales/es/LC_MESSAGES/connies_uploader.po
msgid ""
msgstr ""
"Language: es\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"

msgid "Add Files"
msgstr "Añadir Archivos"

msgid "Start Upload"
msgstr "Iniciar Subida"

msgid "Cancel"
msgstr "Cancelar"

msgid "Upload Complete"
msgstr "Subida Completa"

#, python-format
msgid "%d file uploaded successfully"
msgid_plural "%d files uploaded successfully"
msgstr[0] "%d archivo subido correctamente"
msgstr[1] "%d archivos subidos correctamente"

msgid "Service"
msgstr "Servicio"

msgid "API Key"
msgstr "Clave API"

msgid "Settings"
msgstr "Configuración"
```

#### Language Selection UI
```python
# Add to settings menu
class LanguageSelectionDialog(ctk.CTkToplevel):
    """Dialog for selecting UI language"""

    SUPPORTED_LANGUAGES = {
        'en': 'English',
        'es': 'Español',
        'fr': 'Français',
        'de': 'Deutsch',
        'zh_CN': '简体中文',
        'ja': '日本語',
        'pt_BR': 'Português (Brasil)'
    }

    def __init__(self, parent):
        super().__init__(parent)

        self.title(_("Select Language"))
        self.geometry("300x400")

        label = ctk.CTkLabel(self, text=_("Choose UI Language:"))
        label.pack(pady=10)

        for lang_code, lang_name in self.SUPPORTED_LANGUAGES.items():
            btn = ctk.CTkButton(
                self,
                text=lang_name,
                command=lambda lc=lang_code: self._change_language(lc)
            )
            btn.pack(pady=5, padx=20, fill='x')

    def _change_language(self, language_code: str):
        """Change app language and restart UI"""
        # Save preference
        config = ConfigLoader().load()
        config.ui.language = language_code
        config.save()

        # Show restart message
        messagebox.showinfo(
            _("Language Changed"),
            _("Please restart the application for changes to take effect.")
        )

        self.destroy()
```

### Translation Coverage Areas
1. **Main Window**: Buttons, labels, menu items
2. **Dialogs**: Error messages, confirmations, progress
3. **Settings**: All configuration options
4. **Upload Messages**: Status updates, error messages
5. **Help Text**: Tooltips, instructions

### Dependencies
- **babel**: Enhanced i18n support (optional but recommended)
- **polib**: For programmatic .po file manipulation (optional)

### Effort Estimate
- **Complexity**: Medium
- **Time**: 5-6 days
  - 2 days: Framework setup, text extraction
  - 1 day: UI refactoring to use translation functions
  - 2-3 days: Initial translations (need native speakers or translation service)
- **Files Affected**: Nearly all Python files (add `_()` calls), new `locales/` directory

### Success Criteria
- ✅ Support for 5+ languages (EN, ES, FR, DE, ZH)
- ✅ All UI text is translatable (no hardcoded strings)
- ✅ Language selection in Settings menu
- ✅ Language preference persists across sessions
- ✅ Proper plural form handling for all languages

### Translation Strategy
1. **Phase 1**: Extract all translatable strings, create .pot template
2. **Phase 2**: Generate initial translations using DeepL API or Google Translate
3. **Phase 3**: Recruit native speakers for review/refinement
4. **Phase 4**: Community contribution system for new languages

---

## 6. Plugin System for Custom Services

### Overview
Implement a plugin architecture allowing users and developers to add support for new image hosting services without modifying core code.

### Rationale
- **Current State**: Adding new services requires modifying `api.py` and core application code
- **Gap**: Users cannot add custom/private services; community cannot contribute new services easily
- **Benefit**: Extensibility, community contributions, custom enterprise integrations

### Implementation Approach

#### Plugin Interface
```python
# modules/plugin_interface.py
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from pathlib import Path
import httpx

class ImageHostPlugin(ABC):
    """Base class for image hosting service plugins"""

    # Plugin metadata
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
    allowed_formats: list = ['jpg', 'jpeg', 'png', 'gif', 'webp']

    def __init__(self, credentials: Dict = None):
        """Initialize plugin with credentials"""
        self.credentials = credentials or {}
        self.client: Optional[httpx.Client] = None

    @abstractmethod
    def upload(self, file_path: Path, progress_callback=None) -> Tuple[str, str]:
        """
        Upload image to service.

        Args:
            file_path: Path to image file
            progress_callback: Optional callback(bytes_sent, total_bytes)

        Returns:
            Tuple of (image_url, thumbnail_url)

        Raises:
            UploadException: If upload fails
        """
        pass

    @abstractmethod
    def validate_credentials(self) -> bool:
        """
        Validate provided credentials.

        Returns:
            True if credentials are valid
        """
        pass

    def create_gallery(self, gallery_name: str, image_urls: list) -> Optional[str]:
        """
        Create gallery/album (optional).

        Args:
            gallery_name: Name for the gallery
            image_urls: List of uploaded image URLs

        Returns:
            Gallery URL if supported, None otherwise
        """
        if not self.supports_galleries:
            return None
        raise NotImplementedError("Gallery creation not implemented")

    def get_credential_fields(self) -> Dict:
        """
        Return required credential fields for UI generation.

        Returns:
            Dict mapping field names to metadata:
            {
                'api_key': {'label': 'API Key', 'type': 'password', 'required': True},
                'username': {'label': 'Username', 'type': 'text', 'required': False},
            }
        """
        return {}

    def cleanup(self):
        """Cleanup resources (close connections, etc.)"""
        if self.client:
            self.client.close()
```

#### Example Plugin Implementation
```python
# plugins/imgur_plugin.py
from modules.plugin_interface import ImageHostPlugin
from pathlib import Path
import httpx

class ImgurPlugin(ImageHostPlugin):
    """Plugin for Imgur image hosting"""

    name = "Imgur"
    version = "1.0.0"
    author = "Community"
    description = "Upload images to Imgur.com"
    service_url = "https://imgur.com"

    supports_galleries = True
    requires_authentication = True
    max_file_size_mb = 20

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self.client_id = credentials.get('client_id', '')
        self.client = httpx.Client(
            headers={'Authorization': f'Client-ID {self.client_id}'}
        )

    def upload(self, file_path: Path, progress_callback=None) -> tuple:
        """Upload image to Imgur"""
        with open(file_path, 'rb') as f:
            image_data = f.read()

        response = self.client.post(
            'https://api.imgur.com/3/image',
            data={'image': image_data}
        )

        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.text}")

        data = response.json()['data']
        return (data['link'], data['link'])  # Imgur uses same URL for full and thumb

    def validate_credentials(self) -> bool:
        """Validate Imgur client ID"""
        try:
            response = self.client.get('https://api.imgur.com/3/credits')
            return response.status_code == 200
        except:
            return False

    def create_gallery(self, gallery_name: str, image_urls: list) -> str:
        """Create Imgur album"""
        image_ids = [url.split('/')[-1].split('.')[0] for url in image_urls]

        response = self.client.post(
            'https://api.imgur.com/3/album',
            data={
                'title': gallery_name,
                'ids[]': image_ids
            }
        )

        data = response.json()['data']
        return f"https://imgur.com/a/{data['id']}"

    def get_credential_fields(self) -> dict:
        return {
            'client_id': {
                'label': 'Imgur Client ID',
                'type': 'password',
                'required': True,
                'help_url': 'https://api.imgur.com/oauth2/addclient'
            }
        }
```

#### Plugin Manager
```python
# modules/plugin_manager.py
import importlib.util
from pathlib import Path
from typing import Dict, List, Type
from modules.plugin_interface import ImageHostPlugin

class PluginManager:
    """Manages plugin loading and discovery"""

    def __init__(self, plugin_dir: Path):
        self.plugin_dir = plugin_dir
        self.plugins: Dict[str, Type[ImageHostPlugin]] = {}
        self._load_plugins()

    def _load_plugins(self):
        """Discover and load all plugins from plugin directory"""
        if not self.plugin_dir.exists():
            logger.warning(f"Plugin directory not found: {self.plugin_dir}")
            return

        for plugin_file in self.plugin_dir.glob('*_plugin.py'):
            try:
                plugin_class = self._load_plugin_file(plugin_file)
                if plugin_class:
                    self.plugins[plugin_class.name] = plugin_class
                    logger.info(f"Loaded plugin: {plugin_class.name} v{plugin_class.version}")
            except Exception as e:
                logger.error(f"Failed to load plugin {plugin_file}: {e}")

    def _load_plugin_file(self, plugin_file: Path) -> Type[ImageHostPlugin]:
        """Load plugin class from Python file"""
        spec = importlib.util.spec_from_file_location(
            f"plugin_{plugin_file.stem}",
            plugin_file
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find ImageHostPlugin subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                issubclass(attr, ImageHostPlugin) and
                attr is not ImageHostPlugin):
                return attr

        return None

    def get_plugin(self, service_name: str) -> Type[ImageHostPlugin]:
        """Get plugin class by service name"""
        return self.plugins.get(service_name)

    def list_plugins(self) -> List[Dict]:
        """List all available plugins"""
        return [
            {
                'name': plugin.name,
                'version': plugin.version,
                'author': plugin.author,
                'description': plugin.description,
                'supports_galleries': plugin.supports_galleries,
                'requires_auth': plugin.requires_authentication
            }
            for plugin in self.plugins.values()
        ]
```

#### UI Integration
```python
# In main.py - dynamic service selection
class UploaderApp:
    def __init__(self):
        # Load plugins
        plugin_dir = Path(__file__).parent / 'plugins'
        self.plugin_manager = PluginManager(plugin_dir)

        # Build service list from core + plugins
        self.available_services = [
            'imx.to',
            'pixhost.to',
            'turboimagehost.com',
            'vipr.im'
        ] + [p['name'] for p in self.plugin_manager.list_plugins()]

        # Service dropdown
        self.service_var = ctk.StringVar(value=self.available_services[0])
        self.service_menu = ctk.CTkOptionMenu(
            self,
            values=self.available_services,
            variable=self.service_var,
            command=self._on_service_changed
        )

    def _on_service_changed(self, service_name: str):
        """Update credential fields based on selected service"""
        # Check if it's a plugin service
        plugin = self.plugin_manager.get_plugin(service_name)

        if plugin:
            # Generate credential fields dynamically
            self._build_credential_ui(plugin.get_credential_fields())
```

### Plugin Distribution
```yaml
# Plugin manifest: plugins/imgur_plugin.yaml
name: Imgur
version: 1.0.0
author: Community
description: Upload images to Imgur.com
main: imgur_plugin.py

requirements:
  - httpx>=0.24.0

credentials:
  - name: client_id
    label: Imgur Client ID
    type: password
    required: true
    help_url: https://api.imgur.com/oauth2/addclient
```

### Features
1. **Hot-Loading**: Plugins loaded at runtime without app restart
2. **Credential UI Generation**: Plugin defines required fields, UI generated automatically
3. **Gallery Support Detection**: UI adapts based on plugin capabilities
4. **Version Management**: Plugin version checking and compatibility
5. **Plugin Marketplace**: Future: In-app plugin browser and installer

### Dependencies
- No new dependencies (uses stdlib `importlib`)

### Effort Estimate
- **Complexity**: High (requires architectural changes)
- **Time**: 6-7 days
  - 2 days: Plugin interface design and base implementation
  - 2 days: Plugin manager and loading system
  - 2 days: UI integration (dynamic fields, service selection)
  - 1 day: Example plugins and documentation
- **Files Affected**:
  - `modules/plugin_interface.py` (new)
  - `modules/plugin_manager.py` (new)
  - `main.py` (refactor service selection)
  - `modules/upload_coordinator.py` (use plugins)
  - `plugins/` directory (new)

### Success Criteria
- ✅ Plugin interface is well-documented
- ✅ Plugins loaded automatically from `plugins/` directory
- ✅ At least 2 example plugins (Imgur, Catbox.moe)
- ✅ Credential UI generated dynamically from plugin metadata
- ✅ Core services refactored as plugins (optional)
- ✅ Plugin development guide published

---

## Implementation Priority

### Recommended Order
1. **Integration Tests** (2-3 days)
   - Quick win, immediate value for regression prevention
   - Foundation for all other improvements

2. **Performance Benchmarking** (3-4 days)
   - Validates v2.5 performance claims
   - Prevents future regressions

3. **Upload Resume** (4-5 days)
   - Highest user value
   - Addresses major pain point for large batches

4. **Plugin System** (6-7 days)
   - Enables community contributions
   - Unlocks ecosystem growth

5. **GUI Unit Tests** (4-5 days)
   - Complex setup, but important for UI stability
   - Requires headless testing infrastructure

6. **Multi-Language Support** (5-6 days)
   - Expands user base
   - Requires translation resources

### Total Estimated Effort
**25-34 days** of development work across all improvements.

---

## Contributing

Community contributions welcome for any of these improvements! Please:
1. Open an issue to discuss the approach before implementing
2. Follow the existing code style and architecture
3. Include tests for new functionality
4. Update documentation

---

## References
- **Testing**: `tests/` directory, `TESTING_GUIDE.md`
- **Architecture**: `ANALYSIS_AND_RECOMMENDATIONS.md`
- **Configuration**: `CONFIG_GUIDE.md`, `config.example.yaml`
- **v2.5 Features**: `PR_DESCRIPTION_V2.5.md`

---

**Document Version**: 1.0
**Last Updated**: 2025-12-30
**Status**: Planning Phase
