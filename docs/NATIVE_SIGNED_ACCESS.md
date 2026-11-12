# Native signed-access feasibility

This investigation is restricted to native Hongguo danmaku. **No new unsigned request was sent. No real native message has been obtained. Native availability has not been disproven.** The pending public-metadata follow-up was unloaded when the user requested native-only work.

## Reference architecture, inspected directly

Reviewed [danmaku.js](https://github.com/zfdang/hongguo-open-player/blob/4fee1ca4bce81f1458026b70166c3df8219f1ada/src/server/native/danmaku.js), [danmaku-sign.js](https://github.com/zfdang/hongguo-open-player/blob/4fee1ca4bce81f1458026b70166c3df8219f1ada/src/server/native/danmaku-sign.js), and [playback-device.js](https://github.com/zfdang/hongguo-open-player/blob/4fee1ca4bce81f1458026b70166c3df8219f1ada/src/server/native/playback-device.js). The inspected [redapple signer](https://github.com/loocor/redapple/blob/c8e9252d6f8b0c3b4b5f6872a056708bdd31a304/src/server/native/danmaku-sign.js) is identical to zfdang's. Nothing from these access implementations was executed or installed.

1. `seriesId` is the drama/book identifier; `vid` is the episode/video identifier. The request path contains `vid`; `group_id=vid`, `group_type=30`, `comment_type=20`; `business_param.book_id=seriesId`. Our selected episode mapping is drama `7701328280862854168` → episode `7701328426518465561`, already verified in the site's episode directory.
2. The request obtains a device/install identity, constructs an Android-client query and UA, derives request times from a common clock, and computes its signature headers locally. zfdang can request an anonymous device registration, with a generated-identity fallback; redapple uses a persisted generated identity. Neither inspected danmaku request flow uses a viewer's login cookie, OAuth exchange or account authorization grant. The existence of login-related material elsewhere does not change this function's dependencies.
3. The success gate is `code=0` or the string `"0"` plus an actual `data.data_list`. Each published row is episode-associated through `comment.common.group_id`; text comes from `common.content.text`, and playback milliseconds from `expand.offset_time`, with a `comment.offset_time` fallback. The display renderer converts to seconds. These relationships support native timing semantics, but are not a successful live response in this project.
4. Pagination uses `extra.next_query_danmaku_list_time` and offsets embedded in `common_list_info.cursor`. Explicit `has_more=false` ends the scan. zfdang passes both the next window offset and original cursor; redapple extracts cursor offsets but does not forward the cursor string at the inspected revision. Both bound pages/items and can stop after empty pages; they do not demonstrate a complete historical pool.
5. Their final display lists discard raw IDs/posting times and deduplicate by rounded time plus cleaned text. Those outputs are inadequate as original research records. Our existing adapter retains raw message items, available native IDs, raw posting fields, cursor strings, request context and immutable page evidence. Unknown posting-time units remain unconverted. Missing-ID fallback fingerprints are labeled and are not platform IDs. None of this is claimed as a live POC.

## What 110001 does and does not diagnose

The previous response is preserved unchanged in `output/native_feasibility/original_error_response.json`, with its original evidence path, timestamp and SHA-256:

```json
{"Code":110001,"Message":"未知异常","BaseResp":{"StatusMessage":"unknown error","StatusCode":110001}}
```

Comparing the saved request envelope and the pre-guard collector source with the reference establishes the following omitted conditions:

- The client-signature header set: `X-Gorgon`, `X-Argus`, `X-Ladon`.
- Synchronized request-time context: `_rticket`, `X-Khronos`, `X-SS-Req-Ticket`.
- Device/install identifiers and Android app/version/device context. The old query carried only `aid`.
- Reference transport metadata such as SDK/from-web headers, app UA and JSON Accept. The old client used its honest research UA/public-page defaults.

These are **confirmed differences from the reference, not a server-provided list of mandatory fields**. Historical wire headers were not captured. The server's generic error does not identify a particular failed check or prove whether signatures alone suffice. The old source-duration probe also failed with the actual 168,554 ms; the reference instead uses an expanding artificial window. We cannot attribute the failure to that difference either. An exact server-side cause would require platform diagnostics or a permitted successful request for comparison; neither is available.

## Account access versus client signing

The signer is a reverse-engineered client-signing implementation, not a documented SDK that authenticates the user's account. Owning an account does not transform executing this imitation into the supported flow requested here. The earlier instruction excluding client impersonation/forged signatures remains in force.

A fresh supported-browser inventory exposed only the in-app browser and MCP Apps. The native app service failed to start; Chrome and the mobile app are not accessible through it. No browser profiles, cookies, passwords, auth tokens or app process memory were read. The plugin search for Hongguo/红果/Douyin returned no matches; this does not establish that no integration exists anywhere.

The [creator platform](https://www.shortdramas.com/) publicly offers services for creators/rightsholders; its public page does not document a native VOD danmaku export. The [official Douyin interaction guide](https://developer.open-douyin.com/docs/resource/zh-CN/interaction/develop/douyincloud/guide) describes livestream gameplay callbacks, not this Hongguo episode pool. Third-party self-signing services found in search do not establish an approved account integration and were not used as substitutes.

**The precise current access gap:** there is no connected, supported way to obtain a native response body from the user's official app/session, and no supplied platform-approved integration that authorizes this episode's native pool and performs its request signing. No official permission-scope identifier or native SDK was found; inventing one would be misleading. The user has been asked only whether such partner/export access exists, not for credentials.

Feasibility is therefore **blocked under the currently available access and constraints**, not “Hongguo has no native danmaku.” Reconnecting Chrome would permit inspecting that session, but does not by itself prove that the website exposes the app-native pool. A supported source must return a real episode-associated `text` + `offset_time` record before expansion to 10 dramas can proceed.

## Local change and validation

The `native-danmaku` command no longer constructs an unsigned transport by default. With no explicit permitted integration or authorized capture, it returns `authorized_native_transport_not_connected` before network requests, evidence creation or SQLite writes; `--resume` cannot bypass the guard. Future integrations can use the existing transport boundary once their actual access contract is known. No speculative signer/provider was added.

Reference success-code handling now accepts the explicit string `"0"`; boolean/float values still fail. Future failed-attempt events no longer use a name implying platform-wide unavailability. Existing historical records were not rewritten.

25 native tests passed, including the no-network guard and preservation of IDs/raw data/pagination. The real CLI guard check performed **0 network requests**, added **0 database runs**, and left the research native count at **0**. These are regression checks, not native-data success. Machine-readable details: `output/native_feasibility/access_diagnosis.json`.
