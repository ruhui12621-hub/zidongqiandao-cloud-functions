# Zidong Qiandao Cloud Functions

This repository stores the sanitized source code for the HoYoLAB and Skland Huawei Cloud Functions bundled into the Android app.

- `source-bundle.zip` contains the source folders `hoyolab/` and `skland/`.
- GitHub Actions builds `hoyolab.zip` and `skland.zip` on Linux.
- Skland uses the project's PyInstaller custom-runtime build script.
- Real Cookie, Stoken, Hypergryph tokens, push credentials, passwords, and Huawei Cloud AK/SK must never be committed here.

Every successful push to `main` publishes a versioned GitHub Release with both ZIP packages. The APK project can later download these assets and bundle them under Android `assets`.

The repository is currently public. Only sanitized source and blank example configuration are intended to be stored here.

## Platform account CSV format

The HoYoLAB and Skland FunctionGraph packages use exactly one `accounts.csv` file per platform function. The APK is responsible for reading, validating and updating these files inside the function ZIP package.

The shared header is:

```csv
account_id,platform,server,name,user_id,credential,stuid,stoken,mid,games,enabled,remark
```

- HoYoLAB package path: `config/accounts.csv`; `platform` must be `hoyolab`, and `server` must be `cn` or `os`.
- Skland package path: `code/accounts.csv`; `platform` must be `skland`, and `server` is empty.
- `credential` contains the Cookie for HoYoLAB or Token for Skland.
- `games` contains supported game keys separated by `|`.
- `enabled` is `true` or `false`.
- CSV parsing supports quoted fields; rows are never split using a simple comma operation.
- **CSV is the only account source.** Missing files, invalid headers and malformed rows fail closed. Neither function reads YAML, JSON, per-account temporary files, or legacy account configuration.
- Each enabled row is processed independently. A failure for one account does not prevent later accounts from running.
- Credentials must never be committed to this repository or written to logs. Only account identifiers and display names may appear in execution context logs.
