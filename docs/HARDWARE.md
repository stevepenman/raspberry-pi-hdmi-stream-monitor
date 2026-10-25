# Optional equipment mode

The default demo needs no equipment. This guide describes retained code paths; it is not a record of hardware validation. Use only equipment and images you are permitted to capture. No recordings are included.

## Capture with MJPEG

Use a Raspberry Pi with a supported 64-bit Linux/Python environment, a USB HDMI capture device and a suitable HDMI source. Install the Python dependencies as in the README. Wheel availability on older or 32-bit operating systems is not verified.

In this repository's ignored `.env`, explicitly opt in:

```dotenv
DEMO_MODE=false
STREAM_MODE=mjpeg
VIDEO_SOURCE=0
SERVER_HOST=127.0.0.1
```

Then run `.venv/bin/python -B main.py` **without `--demo`**. Open the viewer locally. The code uses OpenCV's Linux V4L2 backend and requests MJPEG capture at the configured dimensions. Actual negotiated resolution depends on the device. If capture fails, verify the correct `/dev/videoN` index, permissions and supported video formats.

## HLS capture

Install FFmpeg on the target system, for example `sudo apt install ffmpeg` on a compatible Debian-based system. Set:

```dotenv
DEMO_MODE=false
STREAM_MODE=hls
VIDEO_SOURCE=0
SERVER_HOST=127.0.0.1
H264_ENCODER=libx264
H264_VIDEO_BITRATE=1500k
HLS_SEGMENT_SECONDS=2
HLS_LIST_SIZE=6
V4L2_CAPTURE_FPS=30
```

`libx264` is a software encoder option; the application default retains `h264_v4l2m2m`, which requires a compatible hardware encoder. The example template explicitly chooses `libx264`. Inspect `ffmpeg -encoders` on your target before choosing. No automatic encoder fallback is implemented.

Run `.venv/bin/python -B main.py` and open the viewer. The first HLS file request starts FFmpeg; the playlist may initially return 404 while it is being generated. Segments and playlists go in the ignored `hls/` directory by default. Point `HLS_DIR` only at a dedicated output directory: the startup routine deletes existing `.ts` and `.m3u8` files in that directory. Freeze detection does not inspect HLS frames.

`/health` checks FFmpeg, a nonempty playlist, a segment and playlist freshness. It returns 503 before files exist. The monitor checks process exit every ten seconds and attempts a restart; this does not prove successful capture or playback.

The local hls.js file supports compatible browser playback; no internet player fallback is used. Review and update this retained third-party dependency before wider deployment. The bundle identifies itself as version 1.5.15; a dependency security review has not been performed.

## Optional receiver

Install VLC (`cvlc` or `vlc`) or ffplay on the display computer. The receiver only contacts the URL you explicitly supply. With an HLS streamer already running on the same computer:

```bash
.venv/bin/python Pi_Receiver.py --url http://127.0.0.1:5000/hls/stream.m3u8 --fullscreen
```

Use `--player ffplay` to select ffplay. `--restart-delay` defaults to two seconds; `--vlc-cache-ms` defaults to 800. Stop with Ctrl+C. This optional command will launch a player and make HTTP requests to the supplied server; it is not part of the default offline demo.

For shared-token access, set `STREAM_TOKEN` locally on the server and pass `--token` explicitly to the receiver. Use a URL-safe random hexadecimal value. The receiver rewrites the HLS URL to a token path so relative segment URLs carry authentication. The token can appear in process arguments and access logs, although the receiver does not print its command line. Session-based browser login is also available.

LAN access requires an intentional bind-address change with `DEMO_MODE=false`, firewall configuration and access controls. No real network address is supplied here. The built-in Flask server and current authentication are not a production deployment configuration.
