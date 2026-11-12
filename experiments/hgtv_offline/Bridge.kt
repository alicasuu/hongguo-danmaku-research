package com.hgtv.star.core

import org.json.JSONArray
import org.json.JSONObject

/** Offline JSON interface. No registration, HTTP, credential loading, or database code. */
fun main() {
    val request = JSONObject(System.`in`.bufferedReader().readText())
    val output = when (request.getString("operation")) {
        "verify_signing_fixtures" -> {
            // Exactly the upstream fixed vectors; no new device identity or live-ready request.
            SignerTest().matchesPinnedJavaScriptOracleAcrossTimestampVariants()
            val vectors = JSONArray(SignerTest::class.java.getResource("/signing.json")!!.readText())
            JSONObject().put("status", "passed").put("fixture_vectors", vectors.length())
                .put("live_verified", false)
        }
        "parse_rows" -> {
            val rows = request.getJSONArray("rows")
            val items = JSONArray()
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val parsed = parseDanmakuRows(JSONArray().put(row)).singleOrNull() ?: continue
                val comment = row.getJSONObject("comment")
                items.put(JSONObject().put("text", parsed.text).put("offset_ms", parsed.offsetMs)
                    .put("digg_count", parsed.diggCount)
                    .put("original_text", comment.getJSONObject("common").getJSONObject("content").get("text"))
                    .put("original_offset_time", comment.getJSONObject("expand").get("offset_time"))
                    .put("raw_row", row))
            }
            JSONObject().put("rows_seen", rows.length()).put("items", items)
                .put("rows_skipped", rows.length() - items.length()).put("live_verified", false)
        }
        else -> error("Unsupported operation; only offline fixture verification and row parsing are allowed")
    }
    // macOS GUI-launched processes can have an ASCII stdout charset despite UTF-8 input.
    System.out.write((output.toString() + "\n").toByteArray(Charsets.UTF_8))
    System.out.flush()
}
