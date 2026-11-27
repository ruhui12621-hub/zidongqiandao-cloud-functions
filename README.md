# Zidong Qiandao Cloud Functions

This repository stores the sanitized source code for the HoYoLAB and Skland Huawei Cloud Functions bundled into the Android app.

- `source-bundle.zip` contains the source folders `hoyolab/` and `skland/`.
- GitHub Actions builds `hoyolab.zip` and `skland.zip` on Linux.
- Skland uses the project's PyInstaller custom-runtime build script.
- Real Cookie, Stoken, Hypergryph tokens, push credentials, passwords, and Huawei Cloud AK/SK must never be committed here.

Every successful push to `main` publishes a versioned GitHub Release with both ZIP packages. The APK project can later download these assets and bundle them under Android `assets`.

The repository is currently public. Only sanitized source and blank example configuration are intended to be stored here.

## Platform account CSV format

The HoYoLAB and Skland FunctionGraph packages now accept one `accounts.csv` file per platform function. The APK is responsible for reading, validating and updating these files inside the function ZIP package.

The shared header is:

```csv
account_id,platform,name,user_id,credential,stuid,stoken,mid,games,enabled,remark
```

- HoYoLAB package path: `config/accounts.csv`; `platform` is `hoyolab` or `miyoushe_cn`.
- Skland package path: `code/accounts.csv`; `platform` is `skland`.
- `credential` contains the Cookie for HoYoLAB or Token for Skland.
- `games` contains game keys separated by `|`.
- `enabled` is `true` or `false`.
- The CSV is parsed with quoted-field support. Do not split rows or fields using a simple comma split.
- If the CSV file is absent, the function keeps its legacy configuration reader for migration. Once the CSV exists, it is authoritative; an empty or invalid CSV fails closed instead of silently falling back to old credentials.
- The function processes enabled rows independently. A single account failure does not prevent later accounts from running.
- Never publish account CSV files or include their credential values in logs.
