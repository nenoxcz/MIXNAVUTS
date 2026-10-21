package com.mixnavuts.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class ApiException(val status: Int, message: String) : Exception(message)

/** Client for the MIXNAVUTS Engine API (docs/API.md). Plain HttpURLConnection: works on Android and the JVM. */
class MixnavutsApi(
    baseUrl: String,
    private val timeoutMs: Int = 15_000,
) : RoutesApi {
    private val base = baseUrl.trimEnd('/')

    suspend fun places(): PlacesResponse = MixnavutsJson.decodeFromString(get("/v1/places"))

    suspend fun search(query: String, near: Pair<Double, Double>? = null): SearchResponse {
        var path = "/v1/search?q=" + URLEncoder.encode(query, "UTF-8")
        if (near != null) path += "&lat=${near.first}&lon=${near.second}"
        return MixnavutsJson.decodeFromString(get(path))
    }

    override suspend fun routes(request: RouteRequest): RoutesResponse =
        MixnavutsJson.decodeFromString(post("/v1/routes", MixnavutsJson.encodeToString(RouteRequest.serializer(), request)))

    private suspend fun get(path: String): String = request("GET", path, null)

    private suspend fun post(path: String, body: String): String = request("POST", path, body)

    private suspend fun request(method: String, path: String, body: String?): String = withContext(Dispatchers.IO) {
        val connection = URL(base + path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = timeoutMs
            connection.readTimeout = timeoutMs
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) throw ApiException(status, errorMessage(text) ?: "HTTP $status")
            text
        } finally {
            connection.disconnect()
        }
    }

    private fun errorMessage(text: String): String? = runCatching {
        MixnavutsJson.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.content
    }.getOrNull()
}
