package com.shadeai.app

import com.shadeai.app.ui.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CoreResultsPresentationTest {
    private fun payload() = Json.parseToJsonElement("""{
        "processor":"llm","llm":true,"schema_version":1,"action_authorized":false,
        "category":"reminder","intent":"reminder","priority":"default",
        "entities":{"subject":"Полить цветы","location":null,"service":null},
        "time":{"source":"завтра в 07:00","timezone":"Asia/Yekaterinburg",
        "at":"2026-10-19T02:00:00Z","date":null,"resolution":"exact"}
    }""").jsonObject
    private fun edit(key: String, value: JsonElement) = JsonObject(payload() + (key to value))
    private fun time(vararg changes: Pair<String, JsonElement>): JsonObject =
        edit("time", JsonObject(payload().getValue("time").jsonObject + changes.toMap()))

    @Test fun exactTimeUsesResultTimezoneAndContainsOnlyKnownFields() {
        val result = coreProcessing(payload()) as CoreProcessing.Extracted
        assertEquals("19.10.2026 07:00:00", result.fields.toMap()["Распознанное время"])
        assertEquals("Полить цветы", result.fields.toMap()["Событие / дело"])
        assertFalse(result.toString().contains("цветы"))
    }
    @Test fun dateOnlyIsNotShiftedAndUnresolvedPreservesSource() {
        val date = time("at" to JsonNull, "date" to JsonPrimitive("2026-10-19"), "resolution" to JsonPrimitive("date_only"))
        assertEquals("19.10.2026 · время не указано", (coreProcessing(date) as CoreProcessing.Extracted).fields.toMap()["Распознанное время"])
        val unresolved = time("at" to JsonNull, "resolution" to JsonPrimitive("unresolved"), "source" to JsonPrimitive("между 7 и 9"))
        val fields = (coreProcessing(unresolved) as CoreProcessing.Extracted).fields.toMap()
        assertEquals("Точное время не определено", fields["Распознанное время"])
        assertEquals("между 7 и 9", fields["Время в тексте"])
    }
    @Test fun unsupportedVersionActionAndWrongTypesHaveSafeFallback() {
        for (raw in listOf(edit("schema_version", JsonPrimitive(2)), edit("schema_version", JsonPrimitive("1")),
            edit("action_authorized", JsonPrimitive(true)), edit("intent", JsonPrimitive("open_lock")),
            edit("category", JsonPrimitive("private-unknown")), edit("entities", JsonArray(emptyList())),
            JsonPrimitive("private raw output"))) assertSame(CoreProcessing.Unsupported, coreProcessing(raw))
    }
    @Test fun invalidDatesAndNoiseCannotBeShownAsValidExtraction() {
        assertSame(CoreProcessing.Unsupported, coreProcessing(time("at" to JsonPrimitive("2026-02-30T02:00:00Z"))))
        assertSame(CoreProcessing.Unsupported, coreProcessing(time("timezone" to JsonPrimitive("private-zone"))))
        assertSame(CoreProcessing.Unsupported, coreProcessing(time("at" to JsonPrimitive("2026-10-19T24:00:00Z"))))
        assertSame(CoreProcessing.Unsupported, coreProcessing(JsonObject(payload() + mapOf("category" to JsonPrimitive("noise"), "intent" to JsonPrimitive("none"), "priority" to JsonPrimitive("low")))))
    }
    @Test fun diagnosticAndMissingAreSeparateFromModelSuccess() {
        assertSame(CoreProcessing.Missing, coreProcessing(null))
        assertSame(CoreProcessing.Diagnostic, coreProcessing(Json.parseToJsonElement("""{"processor":"diagnostic","llm":false}""")))
        assertSame(CoreProcessing.Unsupported, coreProcessing(Json.parseToJsonElement("""{"processor":"diagnostic","llm":true}""")))
    }
    @Test fun unknownErrorsNeverExposeOriginalContent() {
        assertEquals("Не удалось обработать запись", coreProcessingError("private-exception"))
        assertNull(coreProcessingError(null))
        assertTrue(coreProcessingError("LLM_BAD_RESPONSE")!!.contains("неподтверждённые"))
    }
}
