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

## 48-hour credential validity guard

Both platform functions now use their own existing LTS stream as the only cross-run status source. Each account report is emitted as a structured log line:

```text
[COOKIE_STATUS_JSON]={"platform":"hoyolab","account_id":"...","status":"INVALID","timestamp":"2026-11-27T10:00:00Z","sha256":"...","reason":"..."}
```

- Reports contain only a SHA-256 credential fingerprint, never the Cookie or Token itself.
- The fingerprint is scoped to platform + CSV `account_id` + credential. HoYoLAB Cookie fields are canonicalized so harmless field ordering/spacing changes do not create a new identity.
- On the next run, the function queries only its own LTS stream for the most recent matching `VALID` or `INVALID` report in the preceding 48 hours.
- A latest `INVALID` report is carried forward with a fresh timestamp and all external requests for that account are skipped. A later `VALID` report overrides an earlier invalid report.
- No matching report, a report older than 48 hours, or a different credential fingerprint allows a normal request attempt. Old credentials are not repeatedly reported after the CSV row changes to a new credential.
- LTS query failures are logged as `QUERY_UNAVAILABLE` and fail open, as requested: the function proceeds with the normal request rather than treating an unreadable log as proof of invalidity.
- Existing LTS retention remains 7 days; the guard's trust window is 48 hours.

The APK writes the selected region, project ID, and that platform function's LTS group/stream IDs into FunctionGraph `user_data`, preserving other keys. The runtime does not hardcode a Huawei region.

**IAM requirement:** the FunctionGraph execution agency (`xrole`) must provide the function a temporary IAM token and the minimum LTS permission `lts:logStream:searchLog` for its own stream. No additional paid storage service is introduced. If this permission is absent, the log query will show `QUERY_UNAVAILABLE` and the guard will deliberately allow the request; configure the agency before relying on cross-run blocking.
