import argparse
import shutil
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit


def with_hls_path_token(url: str, token: str | None) -> str:
    """Rewrite http(s)://host/hls/<file> into http(s)://host/hls_t/<token>/<file>.

    This ensures segment URLs resolve under the token path.
    """
    if not token:
        return url

    parts = urlsplit(url)
    path = parts.path or ''
    marker = '/hls/'
    idx = path.find(marker)
    if idx == -1:
        return url

    rest = path[idx + len(marker):].lstrip('/')
    new_path = path[:idx] + f'/hls_t/{quote(token, safe="")}/' + rest
    return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))


def build_vlc_command(url: str, fullscreen: bool, extra_cache_ms: int) -> list[str]:
    # cvlc is the terminal VLC frontend on Raspberry Pi OS.
    cmd = [
        "cvlc",
        "--no-video-title-show",
        "--quiet",
        "--network-caching", str(int(extra_cache_ms)),
        url,
        "vlc://quit",
    ]
    if fullscreen:
        cmd.insert(1, "--fullscreen")
    return cmd


def build_ffplay_command(url: str, fullscreen: bool) -> list[str]:
    cmd = [
        "ffplay",
        "-hide_banner",
        "-loglevel", "error",
        "-autoexit",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-framedrop",
        url,
    ]
    if fullscreen:
        cmd.insert(1, "-fs")
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="HDMI Stream Monitor HLS Receiver for Raspberry Pi (auto-restart).")
    parser.add_argument(
        "--url",
        required=True,
        help="HLS playlist URL, e.g. http://<pi-ip>:5000/hls/stream.m3u8",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional STREAM_TOKEN if the server is protected. Best used with URLs under /hls/.",
    )
    parser.add_argument(
        "--player",
        choices=["vlc", "ffplay"],
        default="vlc",
        help="Player backend to use on the Pi Zero 2.",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Start video fullscreen.",
    )
    parser.add_argument(
        "--restart-delay",
        type=float,
        default=2.0,
        help="Seconds to wait before restarting after the player exits.",
    )
    parser.add_argument(
        "--vlc-cache-ms",
        type=int,
        default=800,
        help="VLC network cache in ms (higher = more stable, more latency).",
    )

    args = parser.parse_args()

    url = with_hls_path_token(args.url, args.token)

    if args.player == "vlc":
        if shutil.which("cvlc") is None and shutil.which("vlc") is None:
            print("VLC not found. Install with: sudo apt-get install -y vlc", file=sys.stderr)
            return 2
        # Prefer cvlc, fall back to vlc if needed.
        if shutil.which("cvlc") is None and shutil.which("vlc") is not None:
            # Replace executable in cmd builder by monkey-patching via prefix.
            def cmd_builder(url: str, fullscreen: bool, extra_cache_ms: int) -> list[str]:
                cmd = build_vlc_command(url, fullscreen, extra_cache_ms)
                cmd[0] = "vlc"
                return cmd
        else:
            cmd_builder = build_vlc_command

        while True:
            cmd = cmd_builder(url, args.fullscreen, args.vlc_cache_ms)
            print('Starting VLC (connection details withheld).')
            try:
                proc = subprocess.run(cmd)
                code = proc.returncode
            except KeyboardInterrupt:
                return 0
            except Exception as e:
                print(f"Failed to run VLC: {e}", file=sys.stderr)
                code = 1

            print(f"VLC exited with code {code}. Restarting in {args.restart_delay}s...")
            time.sleep(args.restart_delay)

    else:
        if shutil.which("ffplay") is None:
            print("ffplay not found. Install with: sudo apt-get install -y ffmpeg", file=sys.stderr)
            return 2

        while True:
            cmd = build_ffplay_command(url, args.fullscreen)
            print('Starting ffplay (connection details withheld).')
            try:
                proc = subprocess.run(cmd)
                code = proc.returncode
            except KeyboardInterrupt:
                return 0
            except Exception as e:
                print(f"Failed to run ffplay: {e}", file=sys.stderr)
                code = 1

            print(f"ffplay exited with code {code}. Restarting in {args.restart_delay}s...")
            time.sleep(args.restart_delay)


if __name__ == "__main__":
    raise SystemExit(main())
