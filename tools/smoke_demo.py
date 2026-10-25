"""Launch the real demo and inspect HTTP responses on loopback only, then stop it."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import json

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    # Deliberately request hardware settings: --demo must override them.
    env.update(DEMO_MODE='false', STREAM_MODE='hls', SERVER_HOST='0.0.0.0',
               SERVER_PORT=str(port), STREAM_TOKEN='', SECRET_KEY='synthetic-smoke-key',
               USERS_FILE='users-smoke-nonexistent.json', LOG_TO_FILE='false',
               STREAM_WIDTH='640', STREAM_HEIGHT='360', TARGET_FPS='5', DEMO_FREEZE='false')
    if (ROOT / env['USERS_FILE']).exists():
        raise RuntimeError('Smoke-test user path must not exist')
    process = subprocess.Popen([sys.executable, '-B', 'main.py', '--demo'], cwd=ROOT,
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    # Bypass proxies so these requests cannot leave the local computer.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise RuntimeError('Demo exited before becoming ready')
            try:
                with opener.open(base + '/health', timeout=1) as response:
                    health = json.load(response)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Demo did not become ready')
                time.sleep(0.1)
        assert health['status'] == 'healthy'
        with opener.open(base + '/', timeout=3) as response:
            assert response.status == 200
        with opener.open(base + '/status', timeout=3) as response:
            status = json.load(response)
            assert status['source'] == 'synthetic' and status['stream_mode'] == 'mjpeg'
        with opener.open(base + '/video_feed', timeout=3) as response:
            assert 'multipart/x-mixed-replace' in response.headers['Content-Type']
            data = response.read(32768)
            start = data.index(b'\xff\xd8')
            end = data.index(b'\xff\xd9', start) + 2
            image = cv2.imdecode(np.frombuffer(data[start:end], np.uint8), cv2.IMREAD_COLOR)
            assert image.shape == (360, 640, 3)
        print('Live loopback demo passed: viewer, status, health and decoded MJPEG frame.')
        print('--demo overrode hardware/HLS settings. Server stopped after this check.')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
