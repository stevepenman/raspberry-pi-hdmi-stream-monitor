# Third-party notices

## hls.js 1.5.15

`static/vendor/hls.min.js` is a retained third-party browser player. Its upstream copyright and licence notices are preserved in `static/vendor/HLSJS_LICENSE.txt`. The complete Apache License 2.0 text is provided in `static/vendor/APACHE-2.0.txt`; these apply to the third-party component, not as a licence grant for the surrounding project.

The bundle was compared byte-for-byte by SHA-256 with the [pinned npm distribution](https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js). Both hashes were:

```text
a91c218fd92b39c2c929b1a08400bc8e85df34a5d474dece920103a2c51675df
```

Upstream [release source](https://github.com/video-dev/hls.js/tree/v1.5.15) and [licence notice](https://github.com/video-dev/hls.js/blob/v1.5.15/LICENSE). The full Apache text was obtained from [the Apache Software Foundation](https://www.apache.org/licenses/LICENSE-2.0.txt). This provenance check is not a vulnerability audit or a recommendation to use this older version in a deployment.

## Python and optional system packages

Flask, Werkzeug, NumPy, OpenCV, bcrypt, python-dotenv and their dependencies retain their own upstream licences. They are installed separately and are not bundled here. FFmpeg, VLC and ffplay are optional external programs, not included binaries. Check their licences and build configurations if you redistribute them.

No project licence or copyright ownership claim has been added. The original workspace's project licence was deliberately not copied because publication and relicensing authority have not been established.
