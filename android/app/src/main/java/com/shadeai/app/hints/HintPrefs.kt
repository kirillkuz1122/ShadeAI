package com.shadeai.app.hints

import android.content.Context
import com.shadeai.app.core.config.ServerPrefs

object HintPrefs {
    private fun prefs(context:Context)=context.getSharedPreferences("shade_local_hints",Context.MODE_PRIVATE)
    @Synchronized fun enabled(context:Context,revision:String=ServerPrefs.revision(context))=
        prefs(context).getString("enabled_revision",null)==revision
    @Synchronized fun set(context:Context,enabled:Boolean,revision:String) {
        check(revision==ServerPrefs.revision(context))
        check(prefs(context).edit().clear().apply {if(enabled)putString("enabled_revision",revision)}.commit())
    }
    @Synchronized fun error(context:Context):String?=if(enabled(context))prefs(context).getString("pause",null) else null
    @Synchronized fun pause(context:Context,revision:String,code:String) {
        if(enabled(context,revision) && revision==ServerPrefs.revision(context))
            check(prefs(context).edit().putString("pause",code).commit())
    }
    @Synchronized fun resume(context:Context) {
        if(enabled(context))check(prefs(context).edit().remove("pause").commit())
    }
    @Synchronized fun cursor(context:Context)=HintCursor(prefs(context).getString("feed",null),prefs(context).getLong("cursor",0))
    @Synchronized fun save(context:Context,revision:String,cursor:HintCursor):Boolean {
        if(!enabled(context,revision) || revision!=ServerPrefs.revision(context))return false
        return prefs(context).edit().putString("feed",cursor.feed).putLong("cursor",cursor.id).commit()
    }
}
