package com.shadeai.app.voice

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicLong

class Microphone(private val context:Context):VoiceRecorder {
    private val generation=AtomicLong(0)
    private val mutex=Mutex()
    override fun stop(){generation.incrementAndGet()}
    @SuppressLint("MissingPermission")
    override suspend fun record():ByteArray {
        val token=generation.get()
        return mutex.withLock {withContext(Dispatchers.IO){
        require(ContextCompat.checkSelfPermission(context,Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)
        check(generation.get()==token)
        val format=AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(16000)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build()
        val minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
        require(minimum>0)
        val recorder=AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(format).setBufferSizeInBytes(maxOf(minimum,4096)).build()
        val pcm=ByteArray(320000)
        var used=0
        try{
            check(recorder.state==AudioRecord.STATE_INITIALIZED)
            recorder.startRecording()
            val deadline=SystemClock.elapsedRealtime()+10000
            while(generation.get()==token && SystemClock.elapsedRealtime()<deadline && used<pcm.size){
                currentCoroutineContext().ensureActive()
                val count=recorder.read(pcm,used,minOf(4096,pcm.size-used),AudioRecord.READ_NON_BLOCKING)
                if(count<0)error("MICROPHONE_UNAVAILABLE")
                if(count>0)used+=count else delay(10)
            }
            pcmWave(pcm,used)
        }finally{
            pcm.fill(0)
            runCatching{recorder.stop()};recorder.release()
        }
    }}
    }
}
