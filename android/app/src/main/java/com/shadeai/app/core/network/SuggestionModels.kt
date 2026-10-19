package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class CoreRuleTrigger(
    val type: String, val kind: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("from_state") val fromState: String, @SerialName("to_state") val toState: String,
    @SerialName("day_group") val dayGroup: String, val timezone: String,
    @SerialName("window_start") val windowStart: String, @SerialName("window_end") val windowEnd: String,
    @SerialName("wraps_midnight") val wrapsMidnight: Boolean,
)
@Serializable
data class CoreRuleAction(@SerialName("entity_id") val entityId: String, val service: String, val params: JsonObject)
@Serializable
data class CoreRuleEvidence(@SerialName("support_days") val supportDays: Int,
    @SerialName("eligible_days") val eligibleDays: Int, @SerialName("dispersion_minutes") val dispersion: Double)
@Serializable
data class CoreRuleHistory(val id: Long, val decision: String, val version: Int,
    @SerialName("target_entity") val target: String? = null, @SerialName("created_at") val createdAt: String)
@Serializable
data class CoreRule(
    val id: String, @SerialName("source_habit_id") val sourceHabitId: String,
    val name: String, val status: String, val version: Int, val trigger: CoreRuleTrigger,
    val action: CoreRuleAction? = null, val evidence: CoreRuleEvidence, val confidence: Double,
    @SerialName("source_current") val sourceCurrent: Boolean,
    @SerialName("approval_valid") val approvalValid: Boolean, val enabled: Boolean, val executable: Boolean,
    @SerialName("executor_status") val executorStatus: String,
    @SerialName("created_at") val createdAt: String, @SerialName("updated_at") val updatedAt: String,
    val history: List<CoreRuleHistory> = emptyList(),
) { override fun toString() = "CoreRule(redacted)" }
@Serializable
data class CoreRulesPage(val automations: List<CoreRule>, val total: Int,
    @SerialName("allowed_targets") val allowedTargets: List<String>, val status: String,
    @SerialName("executor_status") val executorStatus: String,
) { override fun toString() = "CoreRulesPage(redacted)" }
@Serializable
data class RuleDecision(val decision: String, val version: Int,
    @SerialName("target_entity") val target: String? = null)
@Serializable
data class CoreStatus(val status: String)
@Serializable
data class CoreHint(val id: Long, val kind: String,
    @SerialName("notification_id") val notificationId: Long, @SerialName("created_at") val createdAt: String)
@Serializable
data class CoreHintFeed(@SerialName("feed_id") val feedId: String?,
    @SerialName("latest_id") val latestId: Long, @SerialName("next_id") val nextId: Long,
    val hints: List<CoreHint>,
) { override fun toString() = "CoreHintFeed(redacted)" }

interface SuggestionsClient {
    suspend fun list(offset: Int): CoreRulesPage
    suspend fun hints(afterId: Long): CoreHintFeed
    suspend fun detail(id: String): CoreRule
    suspend fun decide(id: String, decision: RuleDecision): CoreRule
    suspend fun refresh(): CoreStatus
}
