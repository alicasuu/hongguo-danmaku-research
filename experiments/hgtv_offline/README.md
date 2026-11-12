# HGTV offline JVM proof of concept

Pinned source: `fy-test/HGTV` commit `3c03c9f27b4f1344378ccf6034063124868d2d14`.
`upstream.json` records the original paths and Git blob hashes. Vendored files are
unchanged and retain the upstream GPL-3.0 license in `vendor/LICENSE`.

## Scope and demonstrated result

The signer/parser subset builds on macOS ARM64 with the existing OpenJDK 22.0.2,
Kotlin 2.1.20, and JVM target 17. This is not a build of the Android application or
the entire core module. No Android SDK, emulator, or physical device is used.

- 5 unchanged upstream JUnit tests pass, including 12 pinned signing vectors.
- The upstream parser fixture has 6 rows; 2 are accepted and 4 skipped.
- 4 Python bridge tests pass: fixture signing, Chinese text/raw-field preservation,
  network permission denial, and rejection of live-collection operations.
- These are repository fixtures, not newly collected Hongguo records.
- Real native records collected/inserted: 0. Production SQLite is unchanged.

## Reproduce

Run from the crawler project root:

```sh
python3 experiments/hgtv_offline/build.py --offline
python3 experiments/hgtv_offline/bridge.py test
python3 -m unittest discover -s experiments/hgtv_offline -p test_bridge.py -v
python3 experiments/hgtv_offline/bridge.py verify-signing
```

On a fresh checkout, run `build.py` without `--offline` once to download the pinned
compiler/dependency jars from Maven Central into this directory's `.deps/`.
It checks upstream Git blob hashes and dependency checksums; subsequent offline
builds require the saved SHA-256 lock. Nothing is installed globally.

## Python interface

`bridge.py parse-rows` reads one JSON array of `data.data_list` rows from stdin and
returns one JSON object. The callable `parse_rows(rows)` provides the same API.
`verify_signing_fixtures()` evaluates only the upstream fixed signing vectors;
there is no general signing or live-request operation exposed by the bridge.

Parsed output includes normalized text/offset/likes alongside `original_text`,
`original_offset_time`, and the complete `raw_row`. IDs and posting times, when
present, remain in that original row; missing values are not invented. Object
serialization is not byte-for-byte HTTP evidence. The caller must preserve and
validate the original response, episode identity, business status, provenance,
and timestamp types before using the production importer. Parsing alone does
not authenticate records, and `live_verified` is always false here.

Registration, HTTP transport, media decryption, database access, and credential
loading are excluded from the compiled subset. Tests and bridge execution use a
JVM network/subprocess guard. That guard requires JDK 17–23 and fails closed on
unsupported JVMs; do not remove it to make a newer JVM run. Only build-time
dependency download is network-enabled. No new device identities are generated;
the upstream tests use their existing, fixed historical fixture context.

## Still required before one live request

An accepted registered `device_id` and matching `iid`/installation context, plus
the corresponding genuine device/app profile used in both query parameters and
the signing context. HGTV's danmaku method does not attach account cookies or
`x-tt-token`, so a browser login is not a substitute for that context. Whether
the live server currently requires further credentials is untested.

Permission must cover the third-party device context and request-signing flow.
The upstream signer contains fixed Android/app environment assertions; a genuine
device ID alone does not validate those assertions. This experiment neither
provisions that context nor establishes authorization. A future permitted test
would send one first-window request, retain the original response, and validate
text and platform offsets before any SQLite insertion. Full coverage remains
unproven; the upstream documentation describes anonymously sampled hot danmaku.
