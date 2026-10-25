"""Hardware-free regression tests. No external network or player is used."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bcrypt
import cv2
import numpy as np

# Isolate the test process from any developer configuration before import.
os.environ.update(DEMO_MODE='true', STREAM_MODE='mjpeg', SERVER_HOST='127.0.0.1',
                  LOG_TO_FILE='false', STREAM_TOKEN='', SECRET_KEY='synthetic-test-key')
import main as streamer

spec = importlib.util.spec_from_file_location('receiver', Path(__file__).parents[1] / 'Pi_Receiver.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class StreamerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = dict(DEMO_MODE=True, DEMO_FREEZE=False, STREAM_MODE='mjpeg',
                        SERVER_HOST='127.0.0.1', STREAM_TOKEN='', PROTECT_INDEX=True,
                        PROTECT_HEALTH=False, ENABLE_FREEZE_DETECTION=True,
                        FREEZE_CHECK_INTERVAL=1, FREEZE_ALERT_SECONDS=2,
                        STREAM_WIDTH=640, STREAM_HEIGHT=360,
                        USERS_FILE=str(Path(self.temp.name) / 'users.json'),
                        HLS_DIR=self.temp.name, HLS_PLAYLIST='stream.m3u8')
        self.settings = patch.multiple(streamer, **settings)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        streamer.cleanup_camera()
        self.addCleanup(streamer.cleanup_camera)
        streamer._users_cache = None
        streamer._users_mtime = 0
        streamer.last_frame_hash = None
        streamer.freeze_frame_count = 0
        streamer.frame_count = 0
        streamer.stream_frozen = False
        streamer.freeze_detected_time = None
        streamer.freeze_started_at = None
        streamer.app.config.update(TESTING=True)
        self.client = streamer.app.test_client()

    def add_demo_user(self):
        password = 'synthetic-test-password'
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
        Path(streamer.USERS_FILE).write_text(json.dumps({'demo-viewer': hashed}), encoding='utf-8')
        return password

    def test_demo_stream_is_decodable_and_never_opens_hardware_or_processes(self):
        with patch.object(cv2, 'VideoCapture', side_effect=AssertionError('Hardware opened')), \
                patch.object(streamer.subprocess, 'Popen', side_effect=AssertionError('Process started')):
            self.assertTrue(streamer.validate_config())
            response = self.client.get('/video_feed', buffered=False)
            try:
                self.assertEqual(response.status_code, 200)
                chunk = next(response.response)
                jpeg = chunk.split(b'\r\n\r\n', 1)[1].rsplit(b'\r\n', 1)[0]
                decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                self.assertEqual(decoded.shape, (360, 640, 3))
            finally:
                response.close()
            self.assertEqual(streamer.active_mjpeg_clients, 0)
            self.assertEqual(self.client.get('/health').status_code, 200)
            self.assertEqual(self.client.get('/health').json['checks']['encoder'], 'n/a')
            self.assertEqual(self.client.get('/status').json['source'], 'synthetic')
            streamer.start_hls_ffmpeg()  # Defense even if called directly in demo mode.

    def test_synthetic_frames_move_or_remain_static_on_request(self):
        camera = streamer.SyntheticCamera()
        self.assertFalse(np.array_equal(camera.read()[1], camera.read()[1]))
        with patch.object(streamer, 'DEMO_FREEZE', True):
            self.assertTrue(np.array_equal(camera.read()[1], camera.read()[1]))
        camera.release()
        self.assertEqual(camera.read(), (False, None))

    def test_unsafe_demo_configuration_is_rejected(self):
        with patch.object(streamer, 'SERVER_HOST', '0.0.0.0'):
            self.assertFalse(streamer.validate_config())
        with patch.object(streamer, 'STREAM_MODE', 'hls'), patch.object(streamer.shutil, 'which', return_value='ffmpeg'):
            self.assertFalse(streamer.validate_config())
        with patch.object(streamer, 'FREEZE_CHECK_INTERVAL', 0):
            self.assertFalse(streamer.validate_config())

    def test_token_auth_rejects_missing_wrong_and_non_ascii_tokens(self):
        with patch.object(streamer, 'STREAM_TOKEN', 'synthetic-test-token'):
            for headers in ({}, {'X-Auth-Token': 'wrong'}, {'X-Auth-Token': 'incorrect-\u2603'}):
                self.assertEqual(self.client.get('/status', headers=headers).status_code, 401)
            self.assertEqual(self.client.get('/status', headers={
                'Authorization': 'Bearer synthetic-test-token'}).status_code, 200)

    def test_login_logout_and_revoked_user(self):
        password = self.add_demo_user()
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertIn(b'Invalid username or password', self.client.post('/login', data={
            'username': 'demo-viewer', 'password': 'wrong'}).data)
        self.assertEqual(self.client.post('/login', data={
            'username': 'demo-viewer', 'password': password}).status_code, 302)
        self.assertEqual(self.client.get('/status').status_code, 200)
        self.client.get('/logout')
        self.assertEqual(self.client.get('/status').status_code, 401)
        self.client.post('/login', data={'username': 'demo-viewer', 'password': password})
        Path(streamer.USERS_FILE).write_text('{}', encoding='utf-8')
        streamer._users_cache = None
        self.assertEqual(self.client.get('/status').status_code, 200)  # No accounts means auth disabled.
        with patch.object(streamer, 'STREAM_TOKEN', 'synthetic-test-token'):
            self.assertEqual(self.client.get('/status').status_code, 401)

    def test_session_only_auth_also_protects_hls_token_route_and_health(self):
        password = self.add_demo_user()
        with patch.multiple(streamer, STREAM_MODE='hls', DEMO_MODE=False, PROTECT_HEALTH=True), \
                patch.object(streamer, 'start_hls_ffmpeg') as start:
            self.assertEqual(self.client.get('/hls_t/anything/stream.m3u8').status_code, 401)
            self.assertEqual(self.client.get('/health').status_code, 401)
            start.assert_not_called()
            Path(self.temp.name, 'stream.m3u8').write_text('#EXTM3U\n', encoding='utf-8')
            self.client.post('/login', data={'username': 'demo-viewer', 'password': password})
            with self.client.get('/hls_t/anything/stream.m3u8') as response:
                self.assertEqual(response.status_code, 200)

    def test_malformed_user_file_fails_closed(self):
        for content in ('broken-json', '[]', '{"demo-viewer": 123}'):
            Path(streamer.USERS_FILE).write_text(content, encoding='utf-8')
            streamer._users_cache = None
            with self.assertRaises(RuntimeError):
                streamer.load_users()

    def test_freeze_requires_elapsed_time_then_recovers(self):
        frame = np.zeros((64, 64, 3), np.uint8)
        self.assertFalse(streamer.detect_frozen_frame(frame))
        with patch.object(streamer.time, 'monotonic', return_value=10):
            self.assertFalse(streamer.detect_frozen_frame(frame))
        with patch.object(streamer.time, 'monotonic', return_value=11):
            self.assertFalse(streamer.detect_frozen_frame(frame))
        with patch.object(streamer.time, 'monotonic', return_value=12):
            self.assertTrue(streamer.detect_frozen_frame(frame))
        self.assertFalse(np.array_equal(frame, streamer.add_freeze_overlay(frame)))
        self.assertFalse(streamer.detect_frozen_frame(np.full_like(frame, 255)))
        self.assertIsNone(streamer.freeze_detected_time)

    def test_spatial_change_with_same_mean_is_not_frozen(self):
        frame = np.zeros((64, 64, 3), np.uint8)
        frame[:, :32] = 255
        streamer.detect_frozen_frame(frame)
        streamer.detect_frozen_frame(frame)
        self.assertFalse(streamer.detect_frozen_frame(np.flip(frame, axis=1)))
        self.assertEqual(streamer.freeze_frame_count, 0)

    def test_hls_viewer_uses_configured_playlist_and_no_cdn(self):
        with patch.multiple(streamer, STREAM_MODE='hls', HLS_PLAYLIST='example.m3u8'):
            response = self.client.get('/')
            self.assertIn(b'example.m3u8', response.data)
            self.assertNotIn(b'https://', response.data)
            self.assertEqual(self.client.get('/video_feed').status_code, 404)
        self.assertEqual(self.client.get('/hls/stream.m3u8').status_code, 404)

    def test_unopened_source_is_unhealthy(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['checks']['camera'], 'failed')


class ReceiverTests(unittest.TestCase):
    def test_token_rewrite_preserves_relative_segment_base(self):
        result = receiver.with_hls_path_token('http://127.0.0.1:5000/hls/stream.m3u8', 'synthetic token')
        self.assertEqual(result, 'http://127.0.0.1:5000/hls_t/synthetic%20token/stream.m3u8')
        self.assertEqual(receiver.with_hls_path_token('http://127.0.0.1:5000/other', None),
                         'http://127.0.0.1:5000/other')

    def test_player_arguments_are_separate_and_fullscreen_is_supported(self):
        url = 'http://127.0.0.1:5000/hls/stream.m3u8'
        vlc = receiver.build_vlc_command(url, True, 800)
        self.assertEqual(vlc[0], 'cvlc')
        self.assertIn('--fullscreen', vlc)
        self.assertIn(url, vlc)
        self.assertIn('-fs', receiver.build_ffplay_command(url, True))


if __name__ == '__main__':
    unittest.main()
