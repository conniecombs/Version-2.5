# Configuration Guide - Connie's Uploader Ultimate v2.5

Complete guide to customizing application behavior through YAML configuration.

## Table of Contents
- [Quick Start](#quick-start)
- [Configuration File Locations](#configuration-file-locations)
- [Configuration Sections](#configuration-sections)
  - [Network Settings](#network-settings)
  - [UI Settings](#ui-settings)
  - [Threading](#threading)
  - [Performance](#performance)
- [Service-Specific Configuration](#service-specific-configuration)
- [Advanced Topics](#advanced-topics)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Creating Your Configuration

1. **Copy the example:**
   ```bash
   cp config.example.yaml config.yaml
   ```

2. **Edit settings:**
   Open `config.yaml` in your text editor and modify values

3. **Restart application:**
   Changes take effect on next launch (or use Tools → Reload Config)

### Minimal Configuration

```yaml
# Simplest config - increase upload speed
threading:
  imx_threads: 10
  pixhost_threads: 5
```

## Configuration File Locations

The application searches for `config.yaml` in this order:

1. **Current Directory**: `./config.yaml` (highest priority)
2. **User Home**: `~/.connies_uploader/config.yaml`
3. **Explicit Path**: Pass via `ConfigLoader(config_path="/path/to/config.yaml")`

**Note:** Only the first found file is loaded. Create `config.yaml` in the project root for development.

## Configuration Sections

### Network Settings

Controls HTTP behavior, timeouts, and retry logic.

```yaml
network:
  # Standard HTTP timeout (seconds)
  # Increase if you have slow internet or uploads timeout
  timeout_seconds: 60.0

  # Number of retries on network failure
  # Uses exponential backoff (2s, 4s, 8s, ...)
  retry_count: 3

  # Extended timeout for large file uploads (seconds)
  # Should be higher than timeout_seconds
  upload_timeout_seconds: 300.0

  # Upload chunk size (bytes)
  # Larger = faster uploads but more memory
  chunk_size: 8192

  # Enable HTTP/2 support
  # May improve performance on compatible servers
  http2_enabled: true
```

**Recommendations:**
- **Slow Internet:** `timeout_seconds: 120.0`, `retry_count: 5`
- **Fast Internet:** `timeout_seconds: 30.0`, `chunk_size: 16384`
- **Large Files (>10MB):** `upload_timeout_seconds: 600.0`
- **Unstable Connection:** `retry_count: 5` or higher

### UI Settings

Controls interface behavior and appearance.

```yaml
ui:
  # UI refresh interval (milliseconds)
  # Lower = more responsive, higher CPU usage
  # Higher = less responsive, lower CPU usage
  update_interval_ms: 20

  # Thumbnail dimensions [width, height] in pixels
  # Affects memory usage and generation time
  thumbnail_size: [40, 40]

  # Show image previews by default
  # Disable for large batches to save memory
  show_previews_default: true

  # Python recursion limit
  # Increase for very large file lists (5000+ files)
  recursion_limit: 3000
```

**Recommendations:**
- **Slow Computer:** `update_interval_ms: 50`, `show_previews_default: false`
- **Fast Computer:** `update_interval_ms: 10`, `thumbnail_size: [60, 60]`
- **Large Batches (1000+ files):** `show_previews_default: false`, `recursion_limit: 5000`
- **Memory Constrained:** `thumbnail_size: [30, 30]`

### Threading

Controls concurrent upload behavior per service.

```yaml
threading:
  # IMX.to concurrent uploads
  # Higher = faster bulk uploads but more server load
  imx_threads: 5

  # Pixhost.to concurrent uploads
  # Pixhost has lower rate limits, keep moderate
  pixhost_threads: 3

  # TurboImageHost concurrent uploads
  # Keep conservative - server is sensitive to load
  turbo_threads: 2

  # Vipr.im concurrent uploads
  # KEEP AT 1 - server doesn't handle concurrency well
  vipr_threads: 1

  # Thumbnail generation workers
  # Parallel workers for thumbnail creation
  thumbnail_workers: 4
```

**Recommendations by Service:**

| Service | Conservative | Balanced | Aggressive |
|---------|-------------|----------|------------|
| IMX.to | 3 | 5 | 10 |
| Pixhost | 2 | 3 | 5 |
| Turbo | 1 | 2 | 3 |
| Vipr | 1 | 1 | 1 |

**Recommendations by Use Case:**
- **Fast Bulk Upload:** Max threads for your service
- **Avoid Rate Limits:** Use conservative values
- **Server Friendly:** `imx_threads: 3`, `pixhost_threads: 2`
- **Multi-Core CPU:** `thumbnail_workers: 8` or more

### Performance

Fine-tune queue processing and memory management.

```yaml
performance:
  # Max UI updates processed per refresh cycle
  # Higher = UI more responsive during uploads
  ui_queue_batch_size: 20

  # Max progress updates processed per cycle
  # Higher = smoother progress bars
  progress_queue_batch_size: 50

  # Max results processed per cycle
  # Higher = faster result display
  result_queue_batch_size: 10

  # Delay between thumbnail generation with preview (seconds)
  # Prevents UI freezing during batch thumbnail generation
  thumbnail_sleep_with_preview: 0.01

  # Delay between thumbnail generation without preview (seconds)
  # Can be lower when previews are disabled
  thumbnail_sleep_no_preview: 0.001

  # Trigger garbage collection after N files
  # Lower = more frequent GC, lower peak memory
  # Higher = less frequent GC, higher peak memory
  gc_threshold_files: 100
```

**Recommendations:**
- **High-End Computer:** All batch sizes × 2, `gc_threshold_files: 200`
- **Low-End Computer:** All batch sizes ÷ 2, `gc_threshold_files: 50`
- **Large Batches (1000+ files):** `gc_threshold_files: 50`, disable previews
- **Smooth UI:** `ui_queue_batch_size: 50`, `progress_queue_batch_size: 100`

## Service-Specific Configuration

### IMX.to

```yaml
threading:
  imx_threads: 5

network:
  timeout_seconds: 60.0
  retry_count: 3
```

**Notes:**
- Supports galleries (requires API key)
- Generally handles high concurrency well
- Recommended: 5-10 threads for bulk uploads

### Pixhost.to

```yaml
threading:
  pixhost_threads: 3

network:
  timeout_seconds: 90.0  # Higher timeout
  retry_count: 4         # More retries
```

**Notes:**
- Moderate rate limiting
- Gallery support available
- Recommended: 2-5 threads max
- Increase timeout if experiencing failures

### TurboImageHost

```yaml
threading:
  turbo_threads: 2  # Keep low!

network:
  timeout_seconds: 120.0
  retry_count: 5
```

**Notes:**
- Sensitive to high concurrency
- Slower response times
- Recommended: 1-3 threads max
- May need higher timeouts

### Vipr.im

```yaml
threading:
  vipr_threads: 1  # ALWAYS 1!

network:
  timeout_seconds: 60.0
  retry_count: 3
```

**Notes:**
- **DO NOT increase concurrency**
- Server doesn't handle parallel uploads well
- Keep at 1 thread always

## Advanced Topics

### Configuration Precedence

1. **Runtime overrides** (via `loader.set()`)
2. **User config file** (`config.yaml`)
3. **Default values** (hardcoded in dataclasses)

### Partial Configuration

You don't need to specify all values - only override what you need:

```yaml
# Only change network timeout, everything else uses defaults
network:
  timeout_seconds: 120.0
```

### Reloading Configuration

**Via GUI:**
- Tools → Reload Configuration

**Programmatically:**
```python
from modules.config_loader import reload_config
reload_config()
```

### Getting Current Configuration

**Via Python:**
```python
from modules.config_loader import get_config_loader

loader = get_config_loader()
timeout = loader.get('network', 'timeout_seconds')
```

### Saving Configuration

**Programmatically:**
```python
loader.set('network', 'timeout_seconds', 90.0)
loader.save_config('my_config.yaml')
```

### Environment-Specific Configs

```bash
# Development
cp config.yaml config.dev.yaml

# Production
cp config.yaml config.prod.yaml

# Use specific config
python -c "from modules.config_loader import ConfigLoader; ConfigLoader('config.prod.yaml')"
```

## Troubleshooting

### Configuration Not Loading

**Check file location:**
```bash
ls -la config.yaml
```

**Verify YAML syntax:**
```bash
python -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

**Check logs:**
Look for "Loaded configuration from:" message in console

### Values Not Taking Effect

1. **Restart the application** - config loads at startup
2. **Check for typos** in key names
3. **Verify indentation** - YAML is whitespace-sensitive
4. **Check types** - `timeout_seconds` needs a number, not a string

### Invalid YAML

**Symptoms:**
- Application uses all defaults
- Warning message in logs

**Solution:**
```bash
# Validate YAML
python -m yaml config.yaml

# Check for common issues:
# - Tabs instead of spaces
# - Missing colons
# - Unquoted strings with special characters
```

### Performance Issues

**Uploads too slow:**
```yaml
threading:
  imx_threads: 10  # Increase concurrent uploads

network:
  chunk_size: 16384  # Larger chunks
```

**UI freezing:**
```yaml
ui:
  update_interval_ms: 50  # Reduce refresh rate
  show_previews_default: false  # Disable previews

performance:
  thumbnail_sleep_with_preview: 0.05  # More delay
```

**High memory usage:**
```yaml
performance:
  gc_threshold_files: 50  # More frequent GC

ui:
  thumbnail_size: [30, 30]  # Smaller thumbnails
  show_previews_default: false
```

### Network Errors

**Frequent timeouts:**
```yaml
network:
  timeout_seconds: 120.0
  upload_timeout_seconds: 600.0
  retry_count: 5
```

**Connection refused:**
- Check internet connection
- Verify service is online
- Try reducing concurrent threads

## Example Configurations

### Fast Bulk Upload (Stable Internet)

```yaml
network:
  timeout_seconds: 30.0
  retry_count: 3
  chunk_size: 16384

threading:
  imx_threads: 10
  pixhost_threads: 5
  turbo_threads: 3

ui:
  show_previews_default: false  # Faster
  update_interval_ms: 50
```

### Conservative (Unstable Internet)

```yaml
network:
  timeout_seconds: 120.0
  retry_count: 10
  upload_timeout_seconds: 600.0

threading:
  imx_threads: 2
  pixhost_threads: 2
  turbo_threads: 1
```

### Low-End Computer

```yaml
ui:
  update_interval_ms: 100
  thumbnail_size: [30, 30]
  show_previews_default: false

threading:
  thumbnail_workers: 2

performance:
  ui_queue_batch_size: 10
  progress_queue_batch_size: 20
  gc_threshold_files: 50
```

### High-End Computer (Maximum Performance)

```yaml
network:
  chunk_size: 32768
  http2_enabled: true

threading:
  imx_threads: 15
  pixhost_threads: 8
  thumbnail_workers: 12

ui:
  update_interval_ms: 10
  thumbnail_size: [60, 60]

performance:
  ui_queue_batch_size: 50
  progress_queue_batch_size: 100
  gc_threshold_files: 200
```

## Configuration Schema Reference

### Complete Example

```yaml
# Network Settings
network:
  timeout_seconds: 60.0           # float, seconds
  retry_count: 3                  # int, number of retries
  upload_timeout_seconds: 300.0   # float, seconds
  chunk_size: 8192                # int, bytes
  http2_enabled: true             # bool

# UI Settings
ui:
  update_interval_ms: 20          # int, milliseconds
  thumbnail_size: [40, 40]        # list[int, int], pixels
  show_previews_default: true     # bool
  recursion_limit: 3000           # int

# Threading Configuration
threading:
  imx_threads: 5                  # int, 1-20
  pixhost_threads: 3              # int, 1-10
  turbo_threads: 2                # int, 1-5
  vipr_threads: 1                 # int, KEEP AT 1
  thumbnail_workers: 4            # int, 1-16

# Performance Tuning
performance:
  ui_queue_batch_size: 20         # int
  progress_queue_batch_size: 50   # int
  result_queue_batch_size: 10     # int
  thumbnail_sleep_with_preview: 0.01     # float, seconds
  thumbnail_sleep_no_preview: 0.001      # float, seconds
  gc_threshold_files: 100         # int
```

## Support

For configuration issues:
1. Check this guide
2. Validate YAML syntax
3. Check application logs
4. Review [TESTING_GUIDE.md](TESTING_GUIDE.md)
5. Create GitHub issue with `config.yaml` (remove sensitive data)

---

**Last Updated:** Version 2.5
**See Also:** [README.md](README.md), [TESTING_GUIDE.md](TESTING_GUIDE.md)
