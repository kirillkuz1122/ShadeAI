package com.shadeai.app.hints

import com.shadeai.app.core.network.CoreHint
import com.shadeai.app.core.network.CoreHintFeed
import java.time.Instant
import java.util.UUID

class HintCursor(val feed: String?, val id: Long) { override fun toString()="HintCursor(redacted)" }
class HintPlan(val next: HintCursor, val show: List<CoreHint>) { override fun toString()="HintPlan(redacted)" }

fun planHints(feed: CoreHintFeed, cursor: HintCursor, now: Instant): HintPlan {
    val identity=requireNotNull(feed.feedId)
    require(UUID.fromString(identity).toString()==identity && feed.latestId>=0 && feed.nextId>=0 && feed.hints.size<=20)
    var last=0L
    feed.hints.forEach {item ->
        require(item.id>last && item.id<=feed.latestId && item.notificationId>0 && item.kind.length<=64 && item.createdAt.length<=40)
        last=item.id
    }
    if(cursor.feed != identity || cursor.id>feed.latestId)
        return HintPlan(HintCursor(identity,feed.latestId),emptyList())
    require(feed.nextId>=cursor.id && feed.nextId<=feed.latestId)
    var previous=cursor.id
    feed.hints.forEach { item ->
        require(item.id>previous && item.id<=feed.nextId && item.notificationId>0)
        previous=item.id
    }
    require(if(feed.hints.isEmpty())feed.nextId==cursor.id else previous==feed.nextId)
    val show=feed.hints.filter { item ->
        val at=runCatching {Instant.parse(item.createdAt)}.getOrNull()
        item.kind=="arrival_delivery" && at!=null && !at.isBefore(now.minusSeconds(86400)) && !at.isAfter(now.plusSeconds(60))
    }
    return HintPlan(HintCursor(identity,feed.nextId),show)
}
