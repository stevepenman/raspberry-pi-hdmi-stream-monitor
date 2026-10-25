import cv2
from flask import Flask, Response, render_template_string, send_from_directory, request, session, redirect, url_for
import logging
from logging.handlers import RotatingFileHandler
import atexit
import threading
import time
import numpy as np
import os
import subprocess
import sys
import shutil
import json
import secrets
import argparse
import getpass
from pathlib import Path
from functools import wraps
from datetime import timedelta
import hmac
import bcrypt

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name('.env'))
except ImportError:
    pass  # dotenv is optional

# --- Configuration ---
# Load from environment variables with defaults

# The explicit demo command also overrides an existing hardware configuration.
if __name__ == '__main__' and '--demo' in sys.argv:
    os.environ.update(DEMO_MODE='true', STREAM_MODE='mjpeg', SERVER_HOST='127.0.0.1')

DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() in ('true', '1', 'yes')
DEMO_FREEZE = os.getenv('DEMO_FREEZE', 'false').lower() in ('true', '1', 'yes')

# This is usually 0 or 1. You might need to check which device is your capture card.
# If /dev/video0 is your Pi's webcam, this might be /dev/video1 or /dev/video2.
# You can check by running `ls /dev/video*` in your Pi's terminal.
VIDEO_SOURCE = int(os.getenv('VIDEO_SOURCE', '0'))

# Set the resolution you want to stream.
# Requested capture dimensions; actual support depends on the device.
# (1280, 720) or (1920, 1080)
STREAM_WIDTH = int(os.getenv('STREAM_WIDTH', '1280'))
STREAM_HEIGHT = int(os.getenv('STREAM_HEIGHT', '720'))

# Target stream framerate. Lower FPS greatly reduces CPU + Wi-Fi bandwidth.
TARGET_FPS = int(os.getenv('TARGET_FPS', '5'))

# JPEG encoding quality (1-100, higher = better quality but larger file size)
JPEG_QUALITY = int(os.getenv('JPEG_QUALITY', '80'))

# Server configuration
SERVER_HOST = os.getenv('SERVER_HOST', '127.0.0.1')
SERVER_PORT = int(os.getenv('SERVER_PORT', '5000'))

# Streaming mode
# - "mjpeg": OpenCV capture and multipart JPEG responses, also used by the demo
# - "hls": FFmpeg V4L2 capture and H.264 segments, requiring compatible equipment
STREAM_MODE = os.getenv('STREAM_MODE', 'mjpeg').lower()

# HLS (H.264) settings (used when STREAM_MODE == "hls")
HLS_DIR = str((Path(__file__).parent / os.getenv('HLS_DIR', 'hls')).resolve())
HLS_PLAYLIST = os.getenv('HLS_PLAYLIST', 'stream.m3u8')
HLS_SEGMENT_SECONDS = int(os.getenv('HLS_SEGMENT_SECONDS', '2'))
HLS_LIST_SIZE = int(os.getenv('HLS_LIST_SIZE', '6'))

# Many capture devices don't support very low V4L2 capture FPS settings. We capture at a
# safe rate and drop frames in the encoder to reach TARGET_FPS.
V4L2_CAPTURE_FPS = int(os.getenv('V4L2_CAPTURE_FPS', '30'))

# Encoder choice:
# - "h264_v4l2m2m" uses Raspberry Pi hardware encoder (recommended if available)
# - "libx264" uses CPU encoder (works everywhere, higher CPU)
H264_ENCODER = os.getenv('H264_ENCODER', 'h264_v4l2m2m')

# Target bitrate; tune and measure on the intended hardware and network.
H264_VIDEO_BITRATE = os.getenv('H264_VIDEO_BITRATE', '1500k')

# Freeze detection settings (for detecting when HDMI source freezes)
ENABLE_FREEZE_DETECTION = os.getenv('ENABLE_FREEZE_DETECTION', 'True').lower() in ('true', '1', 'yes')
FREEZE_CHECK_INTERVAL = int(os.getenv('FREEZE_CHECK_INTERVAL', '5'))  # Check every N frames
FREEZE_THRESHOLD = float(os.getenv('FREEZE_THRESHOLD', '0.995'))  # Similarity threshold
FREEZE_ALERT_SECONDS = int(os.getenv('FREEZE_ALERT_SECONDS', '2'))  # Seconds before alerting

# Logging settings
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'False').lower() in ('true', '1', 'yes')
LOG_FILE_PATH = os.getenv('LOG_FILE_PATH', 'stream-monitor.log')
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Optional authentication (recommended for anything beyond a trusted LAN)
# Authentication is disabled only when both the token and user mapping are empty.
STREAM_TOKEN = os.getenv('STREAM_TOKEN', '').strip()
PROTECT_INDEX = os.getenv('PROTECT_INDEX', 'True').lower() in ('true', '1', 'yes')
PROTECT_HEALTH = os.getenv('PROTECT_HEALTH', 'False').lower() in ('true', '1', 'yes')
AUTH_COOKIE_NAME = os.getenv('AUTH_COOKIE_NAME', 'stream_monitor_token')

# Session-based login (username / password)
SECRET_KEY = os.getenv('SECRET_KEY', '').strip()
SESSION_LIFETIME_DAYS = int(os.getenv('SESSION_LIFETIME_DAYS', '7'))
USERS_FILE = str(Path(__file__).parent / os.getenv('USERS_FILE', 'users.json'))

# Constants
FREEZE_DETECT_THUMBNAIL_SIZE = 64
MAX_PIXEL_VALUE = 255.0
# --- End Configuration ---

# Set up logging with rotation
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# File handler with rotation (if enabled)
if LOG_TO_FILE:
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT
        )
        file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {LOG_FILE_PATH}")
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")

app = Flask(__name__)

# Configure Flask secret key for sessions
if not SECRET_KEY:
    # Auto-generate a key if none is configured (will change on restart)
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("No SECRET_KEY configured — auto-generated a random key. "
                   "Sessions will be invalidated on restart. "
                   "Set SECRET_KEY in .env for persistent sessions.")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=SESSION_LIFETIME_DAYS)

# Server start time for uptime tracking
server_start_time = time.time()

# Application version
APP_VERSION = "1.1.0"

# ffmpeg process (HLS mode)
ffmpeg_process = None
ffmpeg_monitor_thread = None
ffmpeg_log_thread = None
ffmpeg_should_run = False
ffmpeg_lock = threading.Lock()

# Global camera instance (singleton pattern)
camera = None
camera_lock = threading.Lock()

# Client tracking for MJPEG mode
active_mjpeg_clients = 0
clients_lock = threading.Lock()

# Freeze detection state
last_frame_hash = None
freeze_frame_count = 0
frame_count = 0
stream_frozen = False
freeze_detected_time = None
freeze_started_at = None

def validate_config():
    """Validate configuration and check dependencies before starting."""
    errors = []
    warnings = []
    
    # Validate resolution
    if STREAM_WIDTH < 320 or STREAM_HEIGHT < 240:
        errors.append(f"Resolution too low: {STREAM_WIDTH}x{STREAM_HEIGHT}")
    if STREAM_WIDTH > 3840 or STREAM_HEIGHT > 2160:
        warnings.append(f"Very high resolution may cause performance issues: {STREAM_WIDTH}x{STREAM_HEIGHT}")
    
    # Validate FPS
    if TARGET_FPS < 1 or TARGET_FPS > 60:
        errors.append(f"TARGET_FPS must be between 1 and 60, got: {TARGET_FPS}")
    
    # Validate JPEG quality
    if JPEG_QUALITY < 1 or JPEG_QUALITY > 100:
        errors.append(f"JPEG_QUALITY must be between 1 and 100, got: {JPEG_QUALITY}")
    
    # Validate stream mode
    if STREAM_MODE not in ('mjpeg', 'hls'):
        errors.append(f"STREAM_MODE must be 'mjpeg' or 'hls', got: {STREAM_MODE}")
    if DEMO_MODE and (STREAM_MODE != 'mjpeg' or SERVER_HOST != '127.0.0.1'):
        errors.append('Demo mode requires MJPEG and SERVER_HOST=127.0.0.1. Use --demo to reset both.')
    if FREEZE_CHECK_INTERVAL < 1 or FREEZE_ALERT_SECONDS < 1:
        errors.append('Freeze check interval and alert seconds must be positive.')
    if HLS_SEGMENT_SECONDS < 1 or HLS_LIST_SIZE < 1:
        errors.append('HLS segment seconds and list size must be positive.')
    if Path(HLS_PLAYLIST).name != HLS_PLAYLIST or not HLS_PLAYLIST.endswith('.m3u8'):
        errors.append('HLS_PLAYLIST must be a plain filename ending in .m3u8.')
    
    # Validate freeze detection settings
    if FREEZE_THRESHOLD < 0.9 or FREEZE_THRESHOLD > 1.0:
        warnings.append(f"FREEZE_THRESHOLD should be between 0.9 and 1.0, got: {FREEZE_THRESHOLD}")
    
    # Check for ffmpeg if HLS mode
    if STREAM_MODE == 'hls':
        if shutil.which('ffmpeg') is None:
            errors.append("ffmpeg not found but HLS mode is enabled. Install with: sudo apt-get install -y ffmpeg")
    
    # Check for video device on Linux
    if not DEMO_MODE and sys.platform.startswith('linux'):
        video_device = f"/dev/video{VIDEO_SOURCE}"
        if not Path(video_device).exists():
            warnings.append(f"Video device {video_device} not found. Check VIDEO_SOURCE setting.")
    
    # Security warnings
    if SERVER_HOST == '0.0.0.0':
        warnings.append("Server is binding to all interfaces (0.0.0.0). Ensure your network is trusted or add authentication.")
    
    # Log results
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  ❌ {error}")
        return False
    
    if warnings:
        logger.warning("Configuration warnings:")
        for warning in warnings:
            logger.warning(f"  ⚠️  {warning}")
    
    logger.info("✓ Configuration validation passed")
    return True

class SyntheticCamera:
    """In-memory video source with the small OpenCV capture interface used here."""

    def __init__(self):
        self.opened = True
        self.frame_number = 0

    def isOpened(self):
        return self.opened

    def release(self):
        self.opened = False

    def read(self):
        if not self.opened:
            return False, None
        number = 0 if DEMO_FREEZE else self.frame_number
        frame = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        frame[:] = (25 + (number * 7) % 120, 35, 45)
        x = 30 + (number * 19) % max(1, STREAM_WIDTH - 60)
        cv2.circle(frame, (x, STREAM_HEIGHT // 2), 25, (60, 200, 240), -1)
        cv2.putText(frame, 'SYNTHETIC DEMO - NO LIVE EQUIPMENT', (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f'Frame {number:06d}', (15, STREAM_HEIGHT - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
        self.frame_number += 1
        return True, frame


def initialize_camera():
    """Initializes and configures the USB video capture device."""
    logger.info("Initializing video capture...")
    if DEMO_MODE:
        return SyntheticCamera()
    # Use cv2.CAP_V4L2 for better compatibility on Linux
    cam = cv2.VideoCapture(VIDEO_SOURCE, cv2.CAP_V4L2)
    
    if not cam.isOpened():
        logger.error(f"Could not open video source {VIDEO_SOURCE}.")
        logger.error("Is the capture card plugged in? Try changing VIDEO_SOURCE to 1.")
        return None

    # Set camera properties
    # Set the codec to MJPEG if possible, as it's often more stable for capture
    cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, STREAM_WIDTH)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, STREAM_HEIGHT)
    
    # Check if properties were set
    width = cam.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cam.get(cv2.CAP_PROP_FRAME_HEIGHT)
    logger.info(f"Video source initialized. Streaming at {int(width)}x{int(height)}")
    
    return cam

def get_camera():
    """Get or initialize the shared camera instance (thread-safe singleton)."""
    global camera
    with camera_lock:
        if camera is None or not camera.isOpened():
            camera = initialize_camera()
        return camera

def cleanup_camera():
    """Release camera resources on shutdown."""
    global camera
    with camera_lock:
        if camera is not None:
            logger.info("Releasing camera resources...")
            camera.release()
            camera = None

def ensure_hls_dir():
    os.makedirs(HLS_DIR, exist_ok=True)

# --- User management ---

_users_cache = None
_users_mtime = 0

def load_users() -> dict:
    """Load the users.json file, caching and reloading when it changes."""
    global _users_cache, _users_mtime
    users_path = Path(USERS_FILE)
    if not users_path.exists():
        return {}
    try:
        mtime = users_path.stat().st_mtime
        if _users_cache is not None and mtime == _users_mtime:
            return _users_cache
        with open(users_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()):
            raise ValueError('Expected a mapping of usernames to password hashes')
        _users_cache = loaded
        _users_mtime = mtime
        return _users_cache
    except Exception as e:
        logger.error(f"Failed to load users file: {e}")
        raise RuntimeError('Cannot read configured users file; access is denied') from e

def check_password(username: str, password: str) -> bool:
    """Check a username/password pair against the users file."""
    users = load_users()
    stored_hash = users.get(username)
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception as e:
        logger.error(f"Password check error for user '{username}': {e}")
        return False

def _auth_enabled() -> bool:
    """Return True if any form of authentication is configured."""
    return bool(STREAM_TOKEN) or bool(load_users())

# --- Token helpers (preserved for machine-to-machine / Pi_Receiver.py) ---

def _get_presented_token() -> str | None:
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        value = auth[7:].strip()
        if value:
            return value

    header_token = request.headers.get('X-Auth-Token')
    if header_token:
        return header_token.strip()

    query_token = request.args.get('token')
    if query_token:
        return query_token.strip()

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token.strip()

    return None

def _is_token_authorized() -> bool:
    """Check if the request carries a valid STREAM_TOKEN."""
    if not STREAM_TOKEN:
        return False
    presented = _get_presented_token()
    if not presented:
        return False
    return hmac.compare_digest(presented.encode('utf-8'), STREAM_TOKEN.encode('utf-8'))

def _is_session_authorized() -> bool:
    """Check if the request has a valid Flask login session."""
    return bool(session.get('logged_in')) and session.get('username') in load_users()

def _is_authorized() -> bool:
    """Check if the request is authorized (by session, token, or if auth is disabled)."""
    if not _auth_enabled():
        return True
    if _is_session_authorized():
        return True
    if _is_token_authorized():
        return True
    return False

def _is_authorized_path(token: str) -> bool:
    if not STREAM_TOKEN:
        # Still allow if session-authorized or no auth at all
        return not _auth_enabled() or _is_session_authorized()
    if token is None:
        return _is_session_authorized()
    return hmac.compare_digest(token.encode('utf-8'), STREAM_TOKEN.encode('utf-8'))

def token_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not _auth_enabled():
            return view_func(*args, **kwargs)
        if not _is_authorized():
            return 'Unauthorized', 401
        return view_func(*args, **kwargs)
    return wrapper

def start_hls_ffmpeg():
    """Start ffmpeg to read /dev/videoN and write HLS segments into HLS_DIR."""
    global ffmpeg_process, ffmpeg_should_run, ffmpeg_monitor_thread, ffmpeg_log_thread

    if DEMO_MODE:
        return  # Synthetic demo never starts an external encoder or opens equipment.

    ffmpeg_should_run = True

    with ffmpeg_lock:
        if ffmpeg_process is not None and ffmpeg_process.poll() is None:
            # Ensure monitor thread is alive
            if ffmpeg_monitor_thread is None or not ffmpeg_monitor_thread.is_alive():
                ffmpeg_monitor_thread = threading.Thread(target=monitor_ffmpeg, daemon=True)
                ffmpeg_monitor_thread.start()
            return

    ensure_hls_dir()

    # Clean old segments/playlists (best-effort)
    try:
        for name in os.listdir(HLS_DIR):
            if name.endswith(('.ts', '.m3u8')):
                os.remove(os.path.join(HLS_DIR, name))
    except Exception:
        pass

    device_path = f"/dev/video{VIDEO_SOURCE}"
    playlist_path = os.path.join(HLS_DIR, HLS_PLAYLIST)

    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "v4l2",
        "-framerate", str(int(V4L2_CAPTURE_FPS)),
        "-video_size", f"{int(STREAM_WIDTH)}x{int(STREAM_HEIGHT)}",
        "-i", device_path,
        "-an",
        "-vf", f"fps={int(TARGET_FPS)}",
        "-c:v", H264_ENCODER,
        "-b:v", H264_VIDEO_BITRATE,
        "-maxrate", H264_VIDEO_BITRATE,
        "-bufsize", "4000k",
        "-g", str(int(TARGET_FPS) * 2),
        "-keyint_min", str(int(TARGET_FPS) * 2),
        "-sc_threshold", "0",
        "-f", "hls",
        "-hls_time", str(int(HLS_SEGMENT_SECONDS)),
        "-hls_list_size", str(int(HLS_LIST_SIZE)),
        "-hls_flags", "delete_segments+append_list+independent_segments",
        "-hls_allow_cache", "0",
        playlist_path,
    ]

    logger.info("Starting HLS encoder (ffmpeg)...")
    logger.info(f"HLS playlist: /hls/{HLS_PLAYLIST}")
    try:
        with ffmpeg_lock:
            # Re-check under lock in case multiple clients triggered startup concurrently.
            if ffmpeg_process is not None and ffmpeg_process.poll() is None:
                return
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

        # Start monitoring thread if not already running
        if ffmpeg_monitor_thread is None or not ffmpeg_monitor_thread.is_alive():
            ffmpeg_monitor_thread = threading.Thread(target=monitor_ffmpeg, daemon=True)
            ffmpeg_monitor_thread.start()

        # Drain stderr so ffmpeg can't block if it gets chatty
        if ffmpeg_log_thread is None or not ffmpeg_log_thread.is_alive():
            ffmpeg_log_thread = threading.Thread(target=_drain_ffmpeg_stderr, daemon=True)
            ffmpeg_log_thread.start()

    except FileNotFoundError:
        logger.error("ffmpeg not found. Install it on the Pi: sudo apt-get install -y ffmpeg")
        with ffmpeg_lock:
            ffmpeg_process = None
        ffmpeg_should_run = False

def stop_hls_ffmpeg():
    global ffmpeg_process, ffmpeg_should_run
    ffmpeg_should_run = False

    with ffmpeg_lock:
        if ffmpeg_process is None:
            return
        if ffmpeg_process.poll() is None:
            logger.info("Stopping HLS encoder (ffmpeg)...")
            try:
                ffmpeg_process.terminate()
                ffmpeg_process.wait(timeout=5)
            except Exception:
                try:
                    ffmpeg_process.kill()
                except Exception:
                    pass
        ffmpeg_process = None

def _drain_ffmpeg_stderr():
    """Continuously drain ffmpeg stderr to avoid pipe backpressure."""
    global ffmpeg_process
    while ffmpeg_should_run:
        proc = ffmpeg_process
        if proc is None:
            time.sleep(0.5)
            continue
        stream = proc.stderr
        if stream is None:
            time.sleep(0.5)
            continue
        try:
            for line in stream:
                if not ffmpeg_should_run:
                    break
                text = line.strip()
                if text:
                    logger.warning(f"ffmpeg: {text}")
        except Exception:
            time.sleep(0.5)
        finally:
            time.sleep(0.5)

def monitor_ffmpeg():
    """Monitor ffmpeg process and restart if it crashes."""
    global ffmpeg_process, ffmpeg_should_run
    
    logger.info("Starting ffmpeg health monitor...")
    
    while ffmpeg_should_run:
        with ffmpeg_lock:
            proc = ffmpeg_process
        if proc is None or proc.poll() is not None:
            if ffmpeg_should_run:  # Only restart if we're supposed to be running
                logger.error("ffmpeg process died. Restarting...")
                start_hls_ffmpeg()
        time.sleep(10)  # Check every 10 seconds
    
    logger.info("ffmpeg health monitor stopped")

# Register cleanup function to run on exit
atexit.register(cleanup_camera)
atexit.register(stop_hls_ffmpeg)

def detect_frozen_frame(frame):
    """
    Detect if the HDMI source has frozen by comparing frames.
    Returns True if stream appears frozen, False otherwise.
    """
    global last_frame_hash, freeze_frame_count, frame_count, stream_frozen, freeze_detected_time, freeze_started_at
    
    if not ENABLE_FREEZE_DETECTION:
        return False
    
    frame_count += 1
    
    # Only check every N frames to reduce CPU usage
    if frame_count % FREEZE_CHECK_INTERVAL != 0:
        return stream_frozen
    
    # Compare small thumbnails while retaining spatial image differences.
    try:
        # Resize to small size for faster comparison
        small_frame = cv2.resize(frame, (FREEZE_DETECT_THUMBNAIL_SIZE, FREEZE_DETECT_THUMBNAIL_SIZE))
        frame_hash = small_frame.astype(np.float32)
        
        if last_frame_hash is not None:
            # Calculate similarity (using normalized difference)
            diff = np.abs(frame_hash - last_frame_hash)
            similarity = 1 - float(np.mean(diff)) / MAX_PIXEL_VALUE
            
            if similarity > FREEZE_THRESHOLD:
                freeze_frame_count += 1

                if freeze_started_at is None:
                    freeze_started_at = time.monotonic()
                if time.monotonic() - freeze_started_at >= FREEZE_ALERT_SECONDS:
                    if not stream_frozen:
                        stream_frozen = True
                        freeze_detected_time = time.time()
                        logger.warning("⚠️ FREEZE DETECTED: HDMI source appears to be frozen!")
                        logger.warning(f"Frame similarity: {similarity:.4f} (threshold: {FREEZE_THRESHOLD})")
            else:
                # Reset if we detect motion
                if stream_frozen:
                    logger.info("✓ Stream recovered - motion detected")
                freeze_frame_count = 0
                stream_frozen = False
                freeze_detected_time = None
                freeze_started_at = None
        
        last_frame_hash = frame_hash
        
    except Exception as e:
        logger.error(f"Error in freeze detection: {e}")
    
    return stream_frozen

def add_freeze_overlay(frame):
    """Add a visual warning overlay when stream is frozen."""
    if not stream_frozen or freeze_detected_time is None:
        return frame
    
    # Create a copy to not modify original
    overlay_frame = frame.copy()
    
    # Add semi-transparent red border
    h, w = overlay_frame.shape[:2]
    border_thickness = 10
    cv2.rectangle(overlay_frame, (0, 0), (w, h), (0, 0, 255), border_thickness)
    
    # Calculate freeze duration
    freeze_duration = int(time.time() - freeze_detected_time)
    
    # Add warning text
    warning_text = f"SOURCE FROZEN - {freeze_duration}s"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.5
    thickness = 3
    
    # Get text size for background
    (text_width, text_height), baseline = cv2.getTextSize(warning_text, font, font_scale, thickness)
    
    # Position at top center
    text_x = (w - text_width) // 2
    text_y = 50
    
    # Draw background rectangle
    cv2.rectangle(overlay_frame, 
                  (text_x - 10, text_y - text_height - 10),
                  (text_x + text_width + 10, text_y + baseline + 10),
                  (0, 0, 0), -1)
    
    # Draw text
    cv2.putText(overlay_frame, warning_text, (text_x, text_y), 
                font, font_scale, (0, 0, 255), thickness)
    
    return overlay_frame

def gen_frames():
    """A generator function that yields video frames as JPEG images."""
    global active_mjpeg_clients
    
    # Register this client
    with clients_lock:
        active_mjpeg_clients += 1
        logger.info(f"MJPEG client connected. Active clients: {active_mjpeg_clients}")
    
    try:
        cam = get_camera()
        
        if cam is None:
            logger.error("Camera not initialized. Cannot generate frames.")
            return

        frame_interval = 1.0 / max(1, int(TARGET_FPS))
        next_frame_time = time.time()

        while True:
            # Read a frame from the camera (thread-safe with lock)
            with camera_lock:
                if cam is None or not cam.isOpened():
                    logger.error("Camera disconnected during streaming.")
                    break
                success, frame = cam.read()
            
            if not success:
                logger.warning("Failed to read frame from camera. Re-initializing...")
                # Attempt to re-initialize if reading fails
                with camera_lock:
                    if cam is not None:
                        cam.release()
                cam = get_camera()
                if cam is None:
                    logger.error("Failed to re-initialize camera. Stopping stream.")
                    break
                continue

            try:
                # Detect if the HDMI source has frozen
                detect_frozen_frame(frame)
                
                # Add visual warning if stream is frozen
                if stream_frozen:
                    frame = add_freeze_overlay(frame)
                
                # Encode the frame as JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if not ret:
                    logger.warning("Failed to encode frame as JPEG.")
                    continue

                # Convert the buffer to bytes
                frame_bytes = buffer.tobytes()

                # Yield the frame in the multipart-replace format
                # This is the "magic" that tells the browser to replace the image
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

                # Pace the stream to the target FPS (reduces Wi-Fi bandwidth and CPU load)
                next_frame_time += frame_interval
                sleep_for = next_frame_time - time.time()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_frame_time = time.time()
            except Exception as e:
                logger.error(f"Error during frame generation: {e}")
                break
    finally:
        # Unregister this client
        with clients_lock:
            active_mjpeg_clients -= 1
            logger.info(f"MJPEG client disconnected. Active clients: {active_mjpeg_clients}")

# --- Login / Logout routes ---

LOGIN_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HDMI Stream Monitor — Login</title>
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #e2e8f0;
        }
        .login-card {
            background: rgba(30, 41, 59, 0.85);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 1rem;
            padding: 2.5rem 2rem;
            width: 100%;
            max-width: 380px;
            box-shadow: 0 25px 60px rgba(0,0,0,0.4);
        }
        .login-card h1 {
            font-size: 1.5rem;
            text-align: center;
            margin-bottom: 0.25rem;
        }
        .login-card .subtitle {
            text-align: center;
            color: #94a3b8;
            font-size: 0.85rem;
            margin-bottom: 1.75rem;
        }
        .login-card .icon {
            text-align: center;
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }
        label {
            display: block;
            font-size: 0.8rem;
            font-weight: 600;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 0.65rem 0.85rem;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 0.5rem;
            color: #f1f5f9;
            font-size: 0.95rem;
            margin-bottom: 1rem;
            outline: none;
            transition: border-color 0.2s;
        }
        input:focus { border-color: #3b82f6; }
        button {
            width: 100%;
            padding: 0.7rem;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            border: none;
            border-radius: 0.5rem;
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
            margin-top: 0.25rem;
        }
        button:hover { opacity: 0.9; }
        .error-msg {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #fca5a5;
            padding: 0.6rem 0.8rem;
            border-radius: 0.5rem;
            font-size: 0.85rem;
            margin-bottom: 1rem;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="icon">🎥</div>
        <h1>HDMI Stream Monitor</h1>
        <p class="subtitle">Sign in to view the stream</p>
        {% if error %}
        <div class="error-msg">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <label for="username">Username</label>
            <input type="text" id="username" name="username" autocomplete="username" required autofocus>
            <label for="password">Password</label>
            <input type="password" id="password" name="password" autocomplete="current-password" required>
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page for browser-based users."""
    # If already logged in, go straight to the stream
    if _is_authorized():
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if check_password(username, password):
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            logger.info(f"User '{username}' logged in successfully")
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for user '{username}'")
            error = 'Invalid username or password.'

    return render_template_string(LOGIN_PAGE_HTML, error=error)

@app.route('/logout')
def logout():
    """Clear the login session."""
    username = session.get('username', 'unknown')
    session.clear()
    logger.info(f"User '{username}' logged out")
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Video streaming home page."""
    if _auth_enabled() and PROTECT_INDEX and not _is_authorized():
        return redirect(url_for('login'))

    # If a token was provided and is valid, store it in a cookie so native HLS clients
    # (e.g., Safari) can fetch segments referenced by the playlist without query params.
    response = None

    # This serves a very simple HTML page that displays either MJPEG or HLS.
    if STREAM_MODE.lower() == "hls":
        html_content = """
        <html>
        <head>
            <title>HDMI Stream Monitor Stream</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
                body, html { 
                    margin: 0; 
                    padding: 0; 
                    height: 100%; 
                    overflow: hidden; 
                    background-color: #000;
                }
                video {
                    display: block;
                    width: 100%;
                    height: 100%;
                    object-fit: contain;
                    background: #000;
                }
                .error {
                    color: white;
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding-top: 20%;
                    font-size: 20px;
                }
            </style>
            <script>
                // Load only the local player library; no external fallback.
                function loadScript(src, onload, onerror) {
                    var s = document.createElement('script');
                    s.src = src;
                    s.async = true;
                    s.onload = onload;
                    s.onerror = onerror;
                    document.head.appendChild(s);
                }
            </script>
        </head>
        <body>
            <video id="video" controls autoplay muted playsinline></video>
            <div id="error" class="error" style="display:none;">
                Stream not available. Please check the connection.
            </div>
            <script>
                (function () {
                    var video = document.getElementById('video');
                    var error = document.getElementById('error');

                    var params = new URLSearchParams(window.location.search);
                    var token = params.get('token');
                    var playlist = {{ playlist|tojson }};
                    var src = '/hls/' + encodeURIComponent(playlist);
                    if (token) {
                        // Token-in-path makes segment requests work for clients that don't
                        // propagate query params to referenced media URLs.
                        src = '/hls_t/' + encodeURIComponent(token) + '/' + encodeURIComponent(playlist);
                    }

                    function showError() {
                        video.style.display = 'none';
                        error.style.display = 'block';
                    }

                    function initHls() {
                        if (video.canPlayType('application/vnd.apple.mpegurl')) {
                            video.src = src;
                            return;
                        }
                        if (window.Hls && Hls.isSupported()) {
                            var hlsConfig = { liveSyncDurationCount: 2 };
                            if (token) {
                                hlsConfig.xhrSetup = function (xhr) {
                                    xhr.setRequestHeader('X-Auth-Token', token);
                                };
                            }
                            var hls = new Hls(hlsConfig);
                            hls.loadSource(src);
                            hls.attachMedia(video);
                            hls.on(Hls.Events.ERROR, function () { showError(); });
                            return;
                        }
                        showError();
                    }

                    loadScript("{{ url_for('static', filename='vendor/hls.min.js') }}", initHls, showError);

                    video.addEventListener('error', showError);
                })();
            </script>
        </body>
        </html>
        """
        response = app.make_response(render_template_string(html_content, playlist=HLS_PLAYLIST))
    else:
        html_content = """
        <html>
        <head>
            <title>HDMI Stream Monitor Stream</title>
            <style>
                body, html { 
                    margin: 0; 
                    padding: 0; 
                    height: 100%; 
                    overflow: hidden; 
                    background-color: #000;
                }
                img { 
                    display: block; 
                    width: 100%; 
                    height: 100%; 
                    object-fit: contain; /* 'contain' fits the whole image, 'cover' fills the screen */
                }
                .error {
                    color: white;
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding-top: 20%;
                    font-size: 24px;
                }
            </style>
        </head>
        <body>
            <script>
                (function () {
                    var params = new URLSearchParams(window.location.search);
                    var token = params.get('token');
                    var src = '/video_feed';
                    if (token) {
                        src += '?token=' + encodeURIComponent(token);
                    }
                    var img = document.createElement('img');
                    img.src = src;
                    img.onerror = function () {
                        img.style.display = 'none';
                        document.getElementById('error').style.display = 'block';
                    };
                    document.body.appendChild(img);
                })();
            </script>
            <div id="error" class="error" style="display:none;">
                Camera not available. Please check the connection.
            </div>
        </body>
        </html>
        """
        response = app.make_response(render_template_string(html_content))

    if STREAM_TOKEN and _is_token_authorized() and request.args.get('token'):
        response.set_cookie(
            AUTH_COOKIE_NAME,
            request.args.get('token'),
            httponly=True,
            samesite='Lax',
        )
    return response

@app.route('/video_feed')
@token_required
def video_feed():
    """The video stream itself."""
    if STREAM_MODE.lower() == "hls":
        return "Error: MJPEG endpoint disabled in HLS mode.", 404

    cam = get_camera()
    if cam is None:
        logger.error("Camera not available for video feed request.")
        return "Error: Camera not available. Please check the connection.", 503

    # Create a Response object, streaming the content from our generator
    return Response(
        gen_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/hls/<path:filename>')
@token_required
def hls_files(filename):
    """Serve HLS playlist and segments."""
    if STREAM_MODE.lower() != "hls":
        return "Error: HLS endpoint disabled in MJPEG mode.", 404

    # Ensure ffmpeg is running when a client requests the stream
    start_hls_ffmpeg()
    return send_from_directory(HLS_DIR, filename, conditional=True)

@app.route('/hls_t/<token>/<path:filename>')
def hls_files_token(token, filename):
    """Serve HLS playlist and segments with token embedded in the path.

    This supports clients (and URL resolution rules) that don't carry query params
    from the playlist URL over to segment requests.
    """
    if STREAM_MODE.lower() != 'hls':
        return 'Error: HLS endpoint disabled in MJPEG mode.', 404

    if not _is_authorized_path(token):
        return 'Unauthorized', 401

    start_hls_ffmpeg()
    return send_from_directory(HLS_DIR, filename, conditional=True)

@app.route('/status')
@token_required
def status():
    """Return the current status of the stream including freeze detection."""
    global stream_frozen, freeze_detected_time, frame_count, active_mjpeg_clients
    
    status_data = {
        'camera_connected': camera is not None and camera.isOpened(),
        'stream_frozen': stream_frozen,
        'total_frames': frame_count,
        'freeze_detection_enabled': ENABLE_FREEZE_DETECTION,
        'stream_mode': STREAM_MODE,
        'source': 'synthetic' if DEMO_MODE else 'capture-device',
        'active_clients': active_mjpeg_clients if STREAM_MODE == 'mjpeg' else 'N/A'
    }

    if STREAM_MODE.lower() == "hls":
        status_data['hls_playlist'] = f"/hls/{HLS_PLAYLIST}"
        status_data['ffmpeg_running'] = ffmpeg_process is not None and ffmpeg_process.poll() is None
    
    if stream_frozen and freeze_detected_time:
        status_data['freeze_duration_seconds'] = int(time.time() - freeze_detected_time)
    
    return status_data

@app.route('/health')
def health():
    """Kubernetes/Docker-style health check endpoint.
    
    Returns a simple health status for load balancers and container orchestrators.
    Use /status for more detailed diagnostics.
    """
    uptime_seconds = time.time() - server_start_time
    
    if PROTECT_HEALTH and not _is_authorized():
        return 'Unauthorized', 401

    # Determine if the system is healthy
    camera_ok = camera is not None and camera.isOpened()
    ffmpeg_ok = True
    playlist_ok = None
    segments_ok = None
    playlist_fresh = None

    if STREAM_MODE.lower() == 'hls':
        with ffmpeg_lock:
            ffmpeg_ok = ffmpeg_process is not None and ffmpeg_process.poll() is None

        playlist_path = Path(HLS_DIR) / HLS_PLAYLIST
        playlist_ok = playlist_path.exists() and playlist_path.stat().st_size > 0
        segments_ok = any(Path(HLS_DIR).glob('*.ts'))
        if playlist_ok:
            max_age = max(10, int(HLS_SEGMENT_SECONDS) * int(HLS_LIST_SIZE) * 3)
            playlist_age = time.time() - playlist_path.stat().st_mtime
            playlist_fresh = playlist_age <= max_age

        # In HLS mode, OpenCV camera may never be opened (ffmpeg reads /dev/videoN directly).
        # Health should reflect whether the HLS stream artifacts are available.
        is_healthy = bool(ffmpeg_ok and playlist_ok and segments_ok and (playlist_fresh is not False))
    else:
        is_healthy = bool(camera_ok and ffmpeg_ok)
    
    health_data = {
        'status': 'healthy' if is_healthy else 'unhealthy',
        'version': APP_VERSION,
        'uptime_seconds': int(uptime_seconds),
        'uptime_human': format_uptime(uptime_seconds),
        'checks': {
            'camera': (
                'ok' if camera_ok else 'failed'
            ) if STREAM_MODE.lower() != 'hls' else 'n/a',
            'encoder': ('ok' if ffmpeg_ok else 'failed') if STREAM_MODE.lower() == 'hls' else 'n/a'
        }
    }

    if STREAM_MODE.lower() == 'hls':
        health_data['checks']['hls_playlist'] = 'ok' if playlist_ok else 'failed'
        health_data['checks']['hls_segments'] = 'ok' if segments_ok else 'failed'
        if playlist_fresh is not None:
            health_data['checks']['hls_playlist_fresh'] = 'ok' if playlist_fresh else 'failed'
    
    # Return 503 if unhealthy, 200 if healthy
    return health_data, 200 if is_healthy else 503

def format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable string."""
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    
    return ' '.join(parts)

def add_user_interactive():
    """CLI helper: add a user to the users.json file."""
    users_path = Path(USERS_FILE)
    users = {}
    if users_path.exists():
        with open(users_path, 'r', encoding='utf-8') as f:
            users = json.load(f)

    print("\n--- HDMI Stream Monitor: Add User ---")
    username = input("Username: ").strip()
    if not username:
        print("Error: username cannot be empty.")
        return
    if username in users:
        overwrite = input(f"User '{username}' already exists. Overwrite? (y/N): ").strip().lower()
        if overwrite != 'y':
            print("Cancelled.")
            return

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: password cannot be empty.")
        return
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Error: passwords do not match.")
        return

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    users[username] = hashed

    with open(users_path, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)

    print(f"✓ User '{username}' added to {USERS_FILE}")
    print(f"  Total users: {len(users)}")

def remove_user_interactive():
    """CLI helper: remove a user from the users.json file."""
    users_path = Path(USERS_FILE)
    if not users_path.exists():
        print(f"No users file found at {USERS_FILE}")
        return

    with open(users_path, 'r', encoding='utf-8') as f:
        users = json.load(f)

    if not users:
        print("No users configured.")
        return

    print("\n--- HDMI Stream Monitor: Remove User ---")
    print(f"Current users: {', '.join(users.keys())}")
    username = input("Username to remove: ").strip()
    if username not in users:
        print(f"User '{username}' not found.")
        return

    confirm = input(f"Remove user '{username}'? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return

    del users[username]
    with open(users_path, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)
    print(f"✓ User '{username}' removed. Remaining users: {len(users)}")

def list_users():
    """CLI helper: list all configured users."""
    users_path = Path(USERS_FILE)
    if not users_path.exists():
        print(f"No users file found at {USERS_FILE}")
        return
    with open(users_path, 'r', encoding='utf-8') as f:
        users = json.load(f)
    if not users:
        print("No users configured.")
        return
    print(f"\nConfigured users ({len(users)}):")
    for name in sorted(users.keys()):
        print(f"  • {name}")

if __name__ == '__main__':
    # CLI argument parsing
    parser = argparse.ArgumentParser(description="HDMI Stream Monitor")
    parser.add_argument('--demo', action='store_true', help='Force synthetic MJPEG on loopback only')
    parser.add_argument('--add-user', action='store_true', help='Add a user to users.json and exit')
    parser.add_argument('--remove-user', action='store_true', help='Remove a user from users.json and exit')
    parser.add_argument('--list-users', action='store_true', help='List all configured users and exit')
    args = parser.parse_args()

    if args.add_user:
        add_user_interactive()
        sys.exit(0)
    if args.remove_user:
        remove_user_interactive()
        sys.exit(0)
    if args.list_users:
        list_users()
        sys.exit(0)

    logger.info("="*60)
    logger.info("HDMI Stream Monitor")
    logger.info("="*60)
    
    # Validate configuration
    if not validate_config():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)
    if DEMO_MODE:
        get_camera()
    
    # Log auth status
    users = load_users()
    if users:
        logger.info(f"Authentication: {len(users)} user(s) configured (login required)")
    elif STREAM_TOKEN:
        logger.info("Authentication: STREAM_TOKEN configured (token required)")
    else:
        logger.warning("Authentication: DISABLED — stream is open to anyone on the network")

    logger.info("Starting Flask server...")
    logger.info(f"Server will be accessible at http://{SERVER_HOST}:{SERVER_PORT}")
    logger.info(f"Stream mode: {STREAM_MODE}")
    logger.info(f"Video resolution: {STREAM_WIDTH}x{STREAM_HEIGHT}")
    logger.info(f"Target FPS: {TARGET_FPS}")
    logger.info(f"JPEG quality: {JPEG_QUALITY}%")
    logger.info(f"Freeze detection: {'ENABLED' if ENABLE_FREEZE_DETECTION else 'DISABLED'}")
    if ENABLE_FREEZE_DETECTION:
        logger.info(f"  - Will alert after {FREEZE_ALERT_SECONDS} seconds of no change")
        logger.info(f"  - Similarity threshold: {FREEZE_THRESHOLD}")
        logger.info(f"  - Check /status endpoint for monitoring")

    if STREAM_MODE.lower() == "hls":
        logger.info("HLS notes:")
        logger.info(f"  - Install ffmpeg on the Pi: sudo apt-get install -y ffmpeg")
        logger.info(f"  - Playlist URL: http://{SERVER_HOST}:{SERVER_PORT}/hls/{HLS_PLAYLIST}")
        logger.info(f"  - Encoder: {H264_ENCODER}, bitrate: {H264_VIDEO_BITRATE}")
    
    logger.info("="*60)
    
    # 'host=0.0.0.0' makes the server accessible on your entire network,
    # not just on the Pi itself.
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, threaded=True, debug=False)
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    finally:
        cleanup_camera()
