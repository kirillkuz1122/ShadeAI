package com.shadeai.app

import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.service.NotificationPolicy
import org.junit.Assert.*
import org.junit.Test

class NotificationPolicyTest {
    private val pkg = "ru.ozon.app.android"
    private val chosen = setOf(pkg)

    @Test fun explicitSelectionIsRequired() {
        assertTrue(NotificationPolicy.allows(pkg, "Заказ", "Готов к выдаче", chosen))
        assertFalse(NotificationPolicy.allows(pkg, "Заказ", "Готов", emptySet()))
        assertFalse(NotificationPolicy.allows("com.wildberries.ru", "Заказ", "Готов", chosen))
        assertFalse(NotificationPolicy.allows(pkg, " ", "\n", chosen))
        NotificationSources.catalog.keys.forEach {
            assertTrue(NotificationPolicy.allows(it, "Заказ", "Готов", setOf(it)))
        }
    }

    @Test fun arbitraryAndPrivatePackagesCannotBeOptedIn() {
        listOf("org.telegram.messenger", "com.whatsapp", "com.sberbank.mobile", "ru.sberbankmobile",
            "com.android.mms", "com.google.android.apps.messaging", "unknown.package").forEach {
            assertFalse(it, NotificationPolicy.allows(it, "Заголовок", "Текст", setOf(it)))
        }
    }

    @Test fun sensitiveWordsAreRejectedInBothFields() {
        listOf("КОД 1234", "кодовое слово", "пароль", "ПИН-код", "PaSsWoRd", "OTP", "code", "CVV", "CVC").forEach {
            assertFalse(it, NotificationPolicy.allows(pkg, it, "Доставка", chosen))
            assertFalse(it, NotificationPolicy.allows(pkg, "Доставка", it, chosen))
        }
        assertTrue(NotificationPolicy.allows(pkg, "Посылка", "На складе", chosen))
        assertFalse(NotificationPolicy.allows(pkg, "Приложение", "Sensitive notification content hidden", chosen))
    }
}
