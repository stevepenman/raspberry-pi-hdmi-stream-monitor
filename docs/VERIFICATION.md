# Verification record

Local verification date: **25 October 2026**. This is a record of local checks, not a production or hardware acceptance report.

## Environment

Windows, 64-bit Python 3.14.2, with an isolated `.venv` inside the portfolio folder. Installed direct dependencies: Flask 3.1.3, NumPy 2.5.4, OpenCV headless 4.14.0.94, bcrypt 4.3.0 and python-dotenv 1.2.4. Dependency ranges are retained in `requirements.txt`; this is not a cross-platform lockfile.

The shell's default Python alias could not launch the installed interpreter. Environment creation used the installed Python executable directly, and checks used `.venv\Scripts\python.exe`. The original NumPy 1.x range was replaced with a NumPy 2 range compatible with that interpreter. Dependency installation initially encountered sandbox network restrictions; it completed using authorized package-download access.

## Passed locally

| Check | Result and scope |
| --- | --- |
| `python -B -m unittest discover -s tests -v` | 13 tests passed. Exercises real Flask routes, decodable synthetic JPEG output, moving/static synthetic sources, login/logout, token rejection, session-only HLS and health protection, malformed account data, freeze timing/overlay/recovery, spatial motion and receiver argument construction. |
| `python -B tools/smoke_demo.py` | Started the actual CLI server on an ephemeral loopback port, retrieved viewer/status/health, decoded an MJPEG frame, then stopped the server. Verified that `--demo` overrides hardware/HLS configuration. |
| `python -B tools/check_syntax.py` | All six project Python files compiled in memory. No bytecode output is required. |
| `python -m pip check` | No broken installed dependency requirements. |
| `python -B tools/check_publication.py` | Reviewed publication candidates passed the allowlist and common sensitive-material pattern checks. Ignored local environment/runtime files are outside the publication set. |
| Separate targeted identifier scan | No supplied confidential identifiers remained in publication filenames or text. The search strings and original sensitive values were not added to the public files. |
| Documentation and image review | Local Markdown links checked; generated synthetic PNG visually inspected. Installation, CLI help, API and demonstration commands exercised with the local virtual environment where applicable. |
| Third-party provenance | Bundled hls.js SHA-256 matched the pinned 1.5.15 npm distribution; original notice retained and full Apache 2.0 text included. |
| Git state | Fresh local repository on `main`, no commits and no remote. No original history imported and no push performed. |

The authentication and freeze-overlay defects identified during inspection have regression coverage. An HLS viewer playlist-name defect and an incorrectly reported MJPEG encoder health field were also corrected. The external browser CDN fallback was removed. No failing local test remains in the prepared copy.

## Not verified

- Physical capture cards, HDMI inputs, Raspberry Pi hardware, device permissions and video-format negotiation.
- An actual FFmpeg encoder run, encoder restart under equipment failure, HLS browser playback or receiver playback with VLC/ffplay. Tests mock process startup where appropriate.
- Multi-viewer behavior, long-running reliability, CPU use, bandwidth, latency or operation across a LAN.
- Linux/macOS execution and other Python versions locally. CI targets Windows/Linux and Python 3.11/3.14 but has not run on GitHub yet.
- A clean installation on another computer, dependency vulnerability audit, full security assessment or production deployment.
- Ownership, employment/contract permissions or a legal right to publish. See [PUBLICATION_REVIEW.md](PUBLICATION_REVIEW.md).

The built-in Flask server is a local demonstration server. The health endpoints provide the limited checks described in the README, not proof of correct video delivery or safe equipment operation.

## Repeat the checks

From the portfolio root on Windows:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B tools/smoke_demo.py
.\.venv\Scripts\python.exe -B tools/check_syntax.py
.\.venv\Scripts\python.exe -B tools/check_publication.py
.\.venv\Scripts\python.exe -m pip check
```

On Linux/macOS use `.venv/bin/python` instead. Repeat after changing source, dependencies or publication contents; update this record when evidence changes.
