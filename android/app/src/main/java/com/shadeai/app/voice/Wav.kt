package com.shadeai.app.voice

import java.nio.ByteBuffer
import java.nio.ByteOrder

interface VoiceRecorder {
    suspend fun record():ByteArray
    fun stop()
}
fun pcmWave(pcm:ByteArray,length:Int=pcm.size):ByteArray {
    require(length in 8000..320000 && length<=pcm.size && length%2==0)
    return ByteBuffer.allocate(44+length).order(ByteOrder.LITTLE_ENDIAN).apply{
        put("RIFF".toByteArray(Charsets.US_ASCII));putInt(36+length);put("WAVEfmt ".toByteArray(Charsets.US_ASCII))
        putInt(16);putShort(1);putShort(1);putInt(16000);putInt(32000);putShort(2);putShort(16)
        put("data".toByteArray(Charsets.US_ASCII));putInt(length);put(pcm,0,length)
    }.array()
}
