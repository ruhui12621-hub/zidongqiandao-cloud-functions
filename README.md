# Zidong Qiandao Cloud Functions

This repository stores the sanitized source code for the HoYoLAB and Skland Huawei Cloud Functions bundled into the Android app.

- `source-bundle.zip` contains the source folders `hoyolab/` and `skland/`.
- GitHub Actions builds `hoyolab.zip` and `skland.zip` on Linux.
- Skland uses the project's PyInstaller custom-runtime build script.
- Real Cookie, Stoken, Hypergryph tokens, push credentials, passwords, and Huawei Cloud AK/SK must never be committed here.

Every successful push to `main` publishes a versioned GitHub Release with both ZIP packages. The APK project can later download these assets and bundle them under Android `assets`.

The repository is currently public. Only sanitized source and blank example configuration are intended to be stored here.