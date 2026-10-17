package com.shadeai.app.service

import java.nio.ByteBuffer
import java.security.MessageDigest

object NotificationIdentity {
    fun hash(vararg fields: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        fields.forEach {
            val bytes = it.toByteArray(Charsets.UTF_8)
            digest.update(ByteBuffer.allocate(4).putInt(bytes.size).array())
            digest.update(bytes)
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
