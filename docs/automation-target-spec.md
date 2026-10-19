# Целевой контракт автоматизаций

Это сохранённое ТЗ до TASK-21, **не описание работающего API**. Произвольные CRUD/уведомительные триггеры/params ещё не реализованы. Действующие предложения, решения и подсказки описаны в [api-spec.md](api-spec.md). Сохраняется для дальнейшего проектирования; расхождения не означают готовность функций.

### 4.4. Автоматизации (Automations)

Управление сценариями локальной автоматизации Shade AI: создание, просмотр, обновление и удаление правил реагирования на события.

#### 4.4.1. `GET /automations` — Список автоматизаций

Возвращает список всех зарегистрированных автоматизаций.

##### Заголовки (Headers)
| Заголовок | Тип | Обязательный | Описание |
| :--- | :--- | :--- | :--- |
| `Authorization` | `string` | Да | `Bearer <SHADE_API_KEY>` |

##### Query-параметры
| Параметр | Тип | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `enabled` | `boolean` | `null` | Фильтр по статусу активности (`true` или `false`) |

##### Поля успешного ответа (200 OK)
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `automations` | `array` | Массив объектов автоматизаций |
| `automations[].id` | `string` | Идентификатор автоматизации |
| `automations[].name` | `string` | Название сценария |
| `automations[].trigger` | `object` | Событие-триггер (устройство, время, входящее уведомление) |
| `automations[].condition` | `object` | Дополнительные условия срабатывания |
| `automations[].action` | `object` | Выполняемое действие (вызов сервиса, отправка пуша) |
| `automations[].enabled` | `boolean` | Флаг активности сценария |
| `automations[].created_at` | `string` | Дата создания |
| `automations[].updated_at` | `string` | Дата обновления |

##### Пример cURL-запроса
```bash
curl -X GET "http://<raspberry-pi-ip>:8000/api/v1/automations" \
  -H "Authorization: Bearer <SHADE_API_KEY>"
```

##### Пример ответа (HTTP 200)
```json
{
  "automations": [
    {
      "id": "aut_4f92a11b",
      "name": "Встреча курьера",
      "trigger": {
        "type": "notification",
        "category": "delivery",
        "keywords": ["курьер", "код"]
      },
      "condition": {
        "type": "time_range",
        "after": "10:00",
        "before": "22:00"
      },
      "action": {
        "type": "device_command",
        "entity_id": "light.hallway_entry",
        "command": "turn_on",
        "params": { "brightness": 255 }
      },
      "enabled": true,
      "created_at": "2026-09-10T14:20:00Z",
      "updated_at": "2026-09-15T09:12:00Z"
    }
  ]
}
```

---

#### 4.4.2. `POST /automations` — Создать автоматизацию

Регистрирует новый сценарий автоматизации.

##### Заголовки (Headers)
| Заголовок | Тип | Обязательный | Описание |
| :--- | :--- | :--- | :--- |
| `Authorization` | `string` | Да | `Bearer <SHADE_API_KEY>` |
| `Content-Type` | `string` | Да | `application/json` |

##### Тело запроса (Request Body)
| Поле | Тип | Обязательное | Описание |
| :--- | :--- | :--- | :--- |
| `name` | `string` | Нет | Название сценария |
| `trigger` | `object` | Да | Описание триггера (тип, источник, параметры) |
| `condition` | `object` | Нет | Условия проверки перед выполнением (может быть пустым `{}`) |
| `action` | `object` | Да | Исполняемое действие |
| `enabled` | `boolean` | Нет | Флаг активности (по умолчанию `true`) |

##### Поля успешного ответа (201 Created)
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `id` | `string` | Назначенный идентификатор созданной автоматизации |
| `name` | `string` | Название сценария |
| `trigger` | `object` | Сохраненная конфигурация триггера |
| `condition` | `object` | Сохраненная конфигурация условий |
| `action` | `object` | Сохраненная конфигурация действия |
| `enabled` | `boolean` | Текущий статус |
| `created_at` | `string` | Время создания (ISO 8601) |

##### Пример cURL-запроса
```bash
curl -X POST "http://<raspberry-pi-ip>:8000/api/v1/automations" \
  -H "Authorization: Bearer <SHADE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ночной режим света",
    "trigger": {
      "type": "time",
      "at": "23:00"
    },
    "condition": {
      "type": "device_state",
      "entity_id": "binary_sensor.someone_at_home",
      "state": "on"
    },
    "action": {
      "type": "device_command",
      "entity_id": "light.living_room_ceiling",
      "command": "turn_off",
      "params": {}
    },
    "enabled": true
  }'
```

##### Пример ответа (HTTP 201)
```json
{
  "id": "aut_78c2e99a",
  "name": "Ночной режим света",
  "trigger": {
    "type": "time",
    "at": "23:00"
  },
  "condition": {
    "type": "device_state",
    "entity_id": "binary_sensor.someone_at_home",
    "state": "on"
  },
  "action": {
    "type": "device_command",
    "entity_id": "light.living_room_ceiling",
    "command": "turn_off",
    "params": {}
  },
  "enabled": true,
  "created_at": "2026-09-17T11:10:00Z"
}
```

---

#### 4.4.3. `PUT /automations/{id}` — Обновить автоматизацию

Выполняет обновление параметров существующей автоматизации.

##### Заголовки (Headers)
| Заголовок | Тип | Обязательный | Описание |
| :--- | :--- | :--- | :--- |
| `Authorization` | `string` | Да | `Bearer <SHADE_API_KEY>` |
| `Content-Type` | `string` | Да | `application/json` |

##### Path-параметры
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `id` | `string` | Идентификатор автоматизации |

##### Тело запроса (Request Body)
| Поле | Тип | Обязательное | Описание |
| :--- | :--- | :--- | :--- |
| `name` | `string` | Нет | Новое имя сценария |
| `trigger` | `object` | Нет | Обновленный триггер |
| `condition` | `object` | Нет | Обновленные условия |
| `action` | `object` | Нет | Обновленное действие |
| `enabled` | `boolean` | Нет | Включение / отключение правила |

##### Поля успешного ответа (200 OK)
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `id` | `string` | Идентификатор автоматизации |
| `name` | `string` | Обновленное имя |
| `trigger` | `object` | Актуальный триггер |
| `condition` | `object` | Актуальные условия |
| `action` | `object` | Актуальное действие |
| `enabled` | `boolean` | Актуальный статус |
| `updated_at` | `string` | Время обновления (ISO 8601) |

##### Пример cURL-запроса
```bash
curl -X PUT "http://<raspberry-pi-ip>:8000/api/v1/automations/aut_78c2e99a" \
  -H "Authorization: Bearer <SHADE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": false
  }'
```

##### Пример ответа (HTTP 200)
```json
{
  "id": "aut_78c2e99a",
  "name": "Ночной режим света",
  "trigger": {
    "type": "time",
    "at": "23:00"
  },
  "condition": {
    "type": "device_state",
    "entity_id": "binary_sensor.someone_at_home",
    "state": "on"
  },
  "action": {
    "type": "device_command",
    "entity_id": "light.living_room_ceiling",
    "command": "turn_off",
    "params": {}
  },
  "enabled": false,
  "updated_at": "2026-09-17T11:15:45Z"
}
```

---

#### 4.4.4. `DELETE /automations/{id}` — Удалить автоматизацию

Удаляет сценарий автоматизации по указанному ID.

##### Заголовки (Headers)
| Заголовок | Тип | Обязательный | Описание |
| :--- | :--- | :--- | :--- |
| `Authorization` | `string` | Да | `Bearer <SHADE_API_KEY>` |

##### Path-параметры
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `id` | `string` | Идентификатор удаляемой автоматизации |

##### Поля успешного ответа (200 OK или 204 No Content)
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `status` | `string` | Статус операции (`deleted`) |
| `id` | `string` | Идентификатор удаленного сценария |

##### Пример cURL-запроса
```bash
curl -X DELETE "http://<raspberry-pi-ip>:8000/api/v1/automations/aut_78c2e99a" \
  -H "Authorization: Bearer <SHADE_API_KEY>"
```

##### Пример ответа (HTTP 200)
```json
{
  "status": "deleted",
  "id": "aut_78c2e99a"
}
```

---
