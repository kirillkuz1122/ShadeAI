package com.shadeai.app.reminders

import android.content.Context
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.CoreReminder
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

object ReminderPrefs {
    private fun prefs(c:Context)=c.getSharedPreferences("shade_calendar_reminders",Context.MODE_PRIVATE)
    fun enabled(c:Context,revision:String=ServerPrefs.revision(c))=prefs(c).getString("enabled",null)==revision
    fun source(c:Context)=prefs(c).getString("source",null)
    fun error(c:Context)=prefs(c).getString("error",null)
    fun items(c:Context):List<CoreReminder> = runCatching {Json.decodeFromString<List<CoreReminder>>(prefs(c).getString("items","[]")!!)}.getOrDefault(emptyList())
    fun receipts(c:Context)=prefs(c).getStringSet("receipts",emptySet()).orEmpty().toSet()
    fun set(c:Context,on:Boolean,revision:String){
        require(revision==ServerPrefs.revision(c))
        val edit=prefs(c).edit().remove("source").remove("error").remove("items")
        if(prefs(c).getString("revision",null)!=revision)edit.remove("receipts")
        edit.putString("revision",revision)
        if(on)edit.putString("enabled",revision)else edit.remove("enabled")
        check(edit.commit())
    }
    fun save(c:Context,source:String,items:List<CoreReminder>){
        check(prefs(c).edit().putString("source",source).putString("items",Json.encodeToString(items)).remove("error").commit())
    }
    fun pause(c:Context,code:String){check(prefs(c).edit().putString("error",code).commit())}
    fun receipt(c:Context,item:CoreReminder){
        val values=(receipts(c).toList()+reminderReceipt(item)).takeLast(200).toSet()
        check(prefs(c).edit().putStringSet("receipts",values).commit())
    }
}
