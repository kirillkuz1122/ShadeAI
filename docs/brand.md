# Руководство по бренду и визуальному стилю Shade AI

> **Shade AI** — локальный AI-ассистент для умного дома с бескомпромиссным приоритетом приватности.  
> Данный документ фиксирует основы визуальной идентичности, цветовую палитру, типографику, систему иконок и правила построения интерфейса в тёмной теме.

---

## 1. Платформа и ДНК бренда

### 1.1. Название и миссия
- **Название**: Shade AI
- **Позиционирование**: Локальный искусственный интеллект для умного дома с нулевой передачей персональных данных во внешние облака (*Privacy-First Home Intelligence*).
- **Миссия**: Дать пользователю абсолютный контроль над домашней автоматизацией, объединив передовые нейросетевые технологии и приватность локальных вычислений.

### 1.2. Слоган
- **Основной слоган**:
  > **«Твой умный дом. Твои правила.»**

- **Альтернативные варианты слогана**:
  1. *«Интеллект в доме. Приватность в приоритете.»* (Акцент на безопасность и конфиденциальность)
  2. *«Сила AI на страже твоего уюта.»* (Тёплый, семейно-ориентированный акцент)
  3. *«Умный дом без облачных посредников.»* (Технический, независимый посыл)
  4. *«Твоя крепость. Твой локальный разум.»* (Фокус на суверенитет и защиту данных)

### 1.3. Тон коммуникации (Tone of Voice)
- **Технологичный, но тёплый и дружелюбный**: Мы говорим на языке современных технологий без занудства и отчуждённости. Умный дом — это среда уюта и покоя, поэтому холодный корпоративный стиль заменяется теплотой натуральных оттенков и заботливым тоном.
- **Надёжный и открытый**: Честные формулировки о работе локальных моделей, статусах устройств и обработке телеметрии.
- **Лаконичный**: Чёткие ответы, понятные карточки состояний, отсутствие визуального и текстового шума.

### 1.4. Целевая аудитория
- **Энтузиасты умного дома и Self-Hosted**: Владельцы Home Assistant, локальных серверов, микрокомпьютеров (Raspberry Pi, mini-PC), Zigbee/Matter экосистем.
- **Privacy-first пользователи**: Люди, осознанно отказавшиеся от закрытых облачных колонок и камер сторонних корпораций.
- **Семьи и владельцы современного жилья**: Пользователи, которым нужен комфорт, автоматизация сценариев и голосовое/текстовое управление без риска утечки частной жизни.

---

## 2. Цветовая палитра

В отличие от стандартного «холодного AI-синего», палитра **Shade AI** вдохновлена теплом домашнего очага, защищённостью и энергией огня. Глубокий оттенок обожжённого дерева и мягкий сливочный свет создают уютную базу, а пламенный алый и тёплый оранжевый служат динамичными индикаторами активности интеллекта.

### 2.1. Основные цвета

| Цвет | HEX | RGB | Название | Роль в интерфейсе |
|------|-----|-----|----------|-------------------|
| ![#423E3B](https://via.placeholder.com/15/423E3B/000000?text=+) `Charcoal Brown` | `#423E3B` | `66, 62, 59` | Основной тёмный | Базовый цвет поверхностей, тёмные карточки, контрастный фон |
| ![#FF2E00](https://via.placeholder.com/15/FF2E00/000000?text=+) `Scarlet Fire` | `#FF2E00` | `255, 46, 0` | Основной акцент | Кнопки первичных действий (CTA), активные статусы, иконка логотипа, индикаторы тревоги/внимания |
| ![#FEA82F](https://via.placeholder.com/15/FEA82F/000000?text=+) `Orange` | `#FEA82F` | `254, 168, 47` | Вторичный акцент | Градиенты, hover-состояния, предупреждения, вторичные бейджи, теги |
| ![#FFFECB](https://via.placeholder.com/15/FFFECB/000000?text=+) `Cream` | `#FFFECB` | `255, 254, 203` | Светлый контраст | Основной цвет заголовков и акцентного текста на тёмном фоне, фон светлых карточек, фокус-элементы |

### 2.2. Расширенная палитра для тёмной темы

Для построения многоуровневого интерфейса (elevation) основной оттенок `Charcoal Brown` расширяется ступенями глубины:

```
Глубина фона (Background)  ────────►  #221F1E (Canvas / Base)
Слой 1: Основной фон       ────────►  #2B2826 (App Background)
Слой 2: Карточки/Панели    ────────►  #423E3B (Charcoal Brown Base)
Слой 3: Приподнятые блоки  ────────►  #4E4946 (Elevated Card / Hover)
Слой 4: Всплывающие окна   ────────►  #5B5652 (Modal / Popover)
Границы и разделители      ────────►  rgba(255, 254, 203, 0.12)
```

### 2.3. Функциональные статусные цвета
- **Успех (Online / Secure / Ok)**: `#4EBA6F` (Тёплый изумрудный, сохраняет контраст с тёмным фоном)
- **Внимание (Warning / Notice)**: `#FEA82F` (Фирменный Orange)
- **Ошибка / Критическое (Error / Danger)**: `#FF2E00` (Фирменный Scarlet Fire)
- **Инфо / Нейтральное (Info / Offline)**: `#A8A29E` (Приглушённый пепельный)

### 2.4. Матрица контрастности и доступность (WCAG 2.1)
- `Cream` (`#FFFECB`) на `Charcoal Brown` (`#423E3B`): **Контрастность ~ 9.8:1** (соответствует стандарту **AAA** для любого текста).
- `Orange` (`#FEA82F`) на `Charcoal Brown` (`#423E3B`): **Контрастность ~ 5.4:1** (соответствует **AA** для обычного текста и **AAA** для крупного текста/иконок).
- `Scarlet Fire` (`#FF2E00`) используется преимущественно как цвет заливки интерактивных элементов, внутри которых применяется белый (`#FFFFFF`) или кремовый (`#FFFECB`) текст.

---

## 3. CSS-переменные дизайн-системы

Токены организованы по современной 3-уровневой архитектуре: **Primitive** (исходные значения) → **Semantic** (смысловые токены назначения) → **Component** (токены конкретных элементов).

```css
:root {
  /* ==========================================================================
     1. ПРИМИТИВНЫЕ ТОКЕНЫ (Primitive Tokens)
     ========================================================================== */
  
  /* Базовые HEX-значения бренда */
  --shade-color-charcoal-base: #423E3B;
  --shade-color-scarlet-base:  #FF2E00;
  --shade-color-orange-base:   #FEA82F;
  --shade-color-cream-base:    #FFFECB;

  /* Каналы RGB для генерации прозрачностей: rgba(var(--...), alpha) */
  --shade-rgb-charcoal: 66, 62, 59;
  --shade-rgb-scarlet:  255, 46, 0;
  --shade-rgb-orange:   254, 168, 47;
  --shade-rgb-cream:    255, 254, 203;

  /* Ступени глубины для тёмных поверхностей (Elevation) */
  --shade-surface-0: #201E1D; /* Холст приложения */
  --shade-surface-1: #2B2826; /* Базовый фон панелей */
  --shade-surface-2: #423E3B; /* Фирменный Charcoal Brown */
  --shade-surface-3: #4F4A46; /* Приподнятая карточка / Hover */
  --shade-surface-4: #5C5652; /* Модальные окна, тултипы */

  /* Текстовые градации */
  --shade-text-pure:      #FFFFFF;
  --shade-text-cream:     #FFFECB;
  --shade-text-secondary: #D4CEBE;
  --shade-text-muted:     #9A948C;

  /* ==========================================================================
     2. СЕМАНТИЧЕСКИЕ ТОКЕНЫ (Semantic Tokens) - ТЁМНАЯ ТЕМА ПО УМОЛЧАНИЮ
     ========================================================================== */
  
  /* Фоны и поверхности */
  --bg-app:               var(--shade-surface-0);
  --bg-surface:           var(--shade-surface-2);
  --bg-surface-elevated:  var(--shade-surface-3);
  --bg-surface-overlay:   var(--shade-surface-4);
  --bg-subtle:            rgba(var(--shade-rgb-cream), 0.05);

  /* Текст */
  --text-primary:         var(--shade-text-cream);
  --text-secondary:       var(--shade-text-secondary);
  --text-muted:           var(--shade-text-muted);
  --text-on-accent:       #FFFFFF;

  /* Акцентные цвета */
  --accent-primary:       var(--shade-color-scarlet-base);
  --accent-primary-hover: #E02900;
  --accent-secondary:     var(--shade-color-orange-base);
  --accent-secondary-hover:#E69322;
  --accent-glow:          rgba(var(--shade-rgb-scarlet), 0.35);

  /* Границы и разделители */
  --border-subtle:        rgba(var(--shade-rgb-cream), 0.08);
  --border-default:       rgba(var(--shade-rgb-cream), 0.16);
  --border-focus:         var(--shade-color-orange-base);
  --border-accent:        var(--shade-color-scarlet-base);

  /* Статусы */
  --status-success:       #4EBA6F;
  --status-warning:       var(--shade-color-orange-base);
  --status-error:         var(--shade-color-scarlet-base);
  --status-info:          #A8A29E;

  /* Тени и свечения */
  --shadow-sm:  0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow-md:  0 4px 12px rgba(0, 0, 0, 0.5);
  --shadow-lg:  0 12px 28px rgba(0, 0, 0, 0.65);
  --shadow-glow: 0 0 24px -4px var(--accent-glow);

  /* ==========================================================================
     3. КОМПОНЕНТНЫЕ ТОКЕНЫ (Component Tokens)
     ========================================================================== */
  
  /* Кнопки */
  --btn-primary-bg:        var(--accent-primary);
  --btn-primary-text:      #FFFFFF;
  --btn-primary-hover:     var(--accent-primary-hover);
  --btn-secondary-bg:      transparent;
  --btn-secondary-border:  var(--border-default);
  --btn-secondary-text:    var(--text-primary);

  /* Карточки */
  --card-bg:               var(--bg-surface);
  --card-border:           var(--border-subtle);
  --card-radius:           12px;

  /* Поля ввода */
  --input-bg:              var(--shade-surface-1);
  --input-border:          var(--border-default);
  --input-text:            var(--text-primary);
  --input-placeholder:     var(--text-muted);
}
```

---

## 4. Фирменные градиенты и визуальные эффекты

Градиент перетекания **Scarlet Fire → Orange** выражает активное состояние искусственного интеллекта Shade AI (генерация ответа, активный сценарий, работающие датчики, подсветка контура дома).

### 4.1. Основные рецепты градиентов

```css
/* 1. Главный акцентный градиент (Primary Flame Gradient) */
/* Подходит для CTA-кнопок, бейджей, линии прогресса */
--gradient-flame-linear: linear-gradient(135deg, #FF2E00 0%, #FEA82F 100%);

/* 2. Горизонтальный градиент для плашек и разделителей */
--gradient-flame-horizontal: linear-gradient(90deg, #FF2E00 0%, #FEA82F 100%);

/* 3. Атмосферное фоновое свечение (Ambient Radial Glow) */
/* Для подсветки активных устройств, карточек голосового ассистента */
--gradient-glow-radial: radial-gradient(circle at 50% 0%, rgba(255, 46, 0, 0.22) 0%, rgba(254, 168, 47, 0.08) 50%, transparent 80%);

/* 4. Мягкий градиент поверхности (Surface Subtle Sheen) */
/* Для премиального фона карточек первого плана */
--gradient-surface-dark: linear-gradient(180deg, #4A4542 0%, #3C3835 100%);
```

### 4.2. Примеры использования градиентов

#### Градиентная кнопка первичного действия
```css
.shade-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  background: var(--gradient-flame-linear);
  color: #FFFFFF;
  font-family: 'Inter', sans-serif;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(255, 46, 0, 0.35);
  transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
}

.shade-btn-primary:hover {
  transform: translateY(-1px);
  filter: brightness(1.08);
  box-shadow: 0 6px 20px rgba(255, 46, 0, 0.45);
}

.shade-btn-primary:active {
  transform: translateY(0);
  filter: brightness(0.95);
}
```

#### Текстовый градиент для акцентных заголовков
```css
.shade-text-gradient {
  background: linear-gradient(135deg, #FF2E00 0%, #FEA82F 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: inline-block;
  font-weight: 700;
}
```

#### Карточка с активной неоновой каймой (Gradient Border)
```css
.shade-card-active {
  position: relative;
  background: var(--shade-surface-2);
  border-radius: 12px;
  padding: 20px;
  color: var(--text-primary);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.shade-card-active::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: 13px;
  padding: 1px;
  background: linear-gradient(135deg, #FF2E00 0%, #FEA82F 100%);
  -webkit-mask: 
    linear-gradient(#fff 0 0) content-box, 
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
}
```

---

## 5. Типографика

Типографическая система Shade AI оптимизирована под высокую плотность информации, интерфейсы дашбордов умного дома, телеметрию датчиков и программный код.

### 5.1. Шрифтовые гарнитуры

1. **Основной интерфейсный шрифт (Primary Body & Headings)**:
   - **Шрифт**: **Inter** (Google Fonts)
   - **Причина выбора**: Превосходная разборчивость цифр и коротких меток на небольших экранах и настенных планшетах, нейтральный современный геометрический рисунок.
   - **Начертания**: Regular (400), Medium (500), Semi-Bold (600), Bold (700).

2. **Моноширинный шрифт для кода и телеметрии (Monospace / Code / Data)**:
   - **Шрифт**: **JetBrains Mono** (Google Fonts)
   - **Причина выбора**: Отличная читаемость IP-адресов, топиков MQTT, логов нейросети, JSON-конфигураций и времени событий. Поддержка специализированных символов.
   - **Начертания**: Regular (400), Medium (500).

### 5.2. Подключение шрифтов (Google Fonts)

```html
<!-- HTML Head -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

```css
/* CSS Подключение */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
```

### 5.3. Шкала типографики (Type Scale)

| Уровень | Размер (px / rem) | Высота строки (Line-height) | Насыщенность (Weight) | Использование |
|---------|-------------------|-----------------------------|-----------------------|---------------|
| **Display** | `36px` / `2.25rem` | `1.2` (44px) | Bold (700) | Главные экраны, посадочные страницы |
| **Heading 1 (H1)** | `28px` / `1.75rem` | `1.25` (36px) | Bold (700) | Заголовки основных разделов |
| **Heading 2 (H2)** | `22px` / `1.375rem`| `1.3` (28px) | Semi-Bold (600) | Названия комнат, модулей, карточек |
| **Heading 3 (H3)** | `18px` / `1.125rem`| `1.35` (24px) | Semi-Bold (600) | Подзаголовки, виджеты |
| **Body (Default)** | `15px` / `0.9375rem`| `1.5` (22px) | Regular (400) | Основной текст описаний и сообщений |
| **Body Medium** | `15px` / `0.9375rem`| `1.5` (22px) | Medium (500) | Кнопки, выделенный текст |
| **Small / Label** | `13px` / `0.8125rem`| `1.4` (18px) | Medium (500) | Подписи к датчикам, бейджи, подсказки |
| **Code / Data** | `13px` / `0.8125rem`| `1.45` (19px) | Regular (400) / Mono | Логи, MQTT-топики, значения сенсоров |

```css
/* Базовые стили текста */
body {
  font-family: var(--font-sans);
  color: var(--text-primary);
  background-color: var(--bg-app);
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

h1, h2, h3, h4 {
  color: var(--shade-text-cream);
  letter-spacing: -0.015em;
  margin: 0 0 0.5em;
}

code, pre, .sensor-value-mono {
  font-family: var(--font-mono);
  font-feature-settings: "zero" on, "tnum" on; /* Табулярные цифры без смещения */
}
```

---

## 6. Рекомендации по иконкам

Для интерфейса Shade AI используется единый векторный стиль линейных иконок с акцентом на контурность и техническую строгость.

### 6.1. Рекомендуемые библиотеки
- **Основная библиотека**: [**Lucide Icons**](https://lucide.dev/) (строгие геометричные формы, идеальное соответствие шрифту Inter, отличная интеграция с React / Vue / Web Components).
- **Альтернативная библиотека**: [**Phosphor Icons**](https://phosphoricons.com/) (в стиле `Regular` или `Duotone`).

### 6.2. Стандарты использования иконок
1. **Толщина штриха (Stroke Width)**: Фиксированная величина **`1.75px`** или **`2px`** во всей экосистеме. Запрещено смешивать сверхтонкие (`1px`) и жирные (`3px`) штрихи.
2. **Размерная сетка**:
   - `16 × 16 px`: Индикаторы внутри мелких бейджей и полей ввода.
   - `20 × 20 px`: Кнопки действий, пункты меню, вторичные контролы.
   - `24 × 24 px`: Стандартные карточки устройств, навигационная панель.
   - `32 × 32 px`+: Крупные виджеты комнат и дашбордов.
3. **Цветовая дисциплина**:
   - По умолчанию иконка наследует цвет родительского текста: `currentColor`.
   - Активные иконки датчиков/света подсвечиваются цветом `Orange` (`#FEA82F`) или `Scarlet Fire` (`#FF2E00`).
   - Иконки безопасности и приватности (замок, шифрование) используют `Orange` или `Success Green`.
4. **Строгий запрет**: **Категорически запрещено использовать Emoji вместо системных SVG-иконок**. Эмодзи не масштабируются консистентно между ОС (iOS/Android/Linux) и разрушают технологичный стиль.

### 6.3. Примеры типовых иконок Shade AI (Lucide)
- **Приватность и защита**: `ShieldCheck`, `Lock`, `EyeOff`, `HardDrive` (акцент на локальное хранилище).
- **Интеллект и автоматизация**: `Cpu`, `Sparkles`, `Bot`, `Workflow`.
- **Умный дом**: `Home`, `Lightbulb`, `Thermometer`, `Power`, `Wifi`, `Sliders`, `Activity`.

```html
<!-- Пример интеграции иконки с подсветкой активного состояния -->
<span class="shade-icon-badge active">
  <!-- Lucide ShieldCheck SVG -->
  <svg class="shade-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    <path d="m9 12 2 2 4-4"/>
  </svg>
  <span>100% Local</span>
</span>
```

---

## 7. Тёмная тема как основа интерфейса

Тёмная тема является **основным (Default) визуальным режимом** Shade AI. Она обеспечивает комфортную работу ночью, гармонично смотрится на настенных смарт-панелях (не ослепляет комнату) и бережёт заряд OLED-экранов мобильных устройств.

### 7.1. Принцип построения слоёв (Surface Hierarchy)

```
┌─────────────────────────────────────────────────────────────┐
│  ФОН ПРИЛОЖЕНИЯ (Canvas #201E1D)                             │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  БАЗОВАЯ КАРТОЧКА (Charcoal Brown #423E3B)            │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  ПРИПОДНЯТЫЙ БЛОК / ИНПУТ (#4F4A46)              │  │  │
│  │  │  Свечение: Scarlet Fire (#FF2E00)               │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

- Вместо резких белых линий используются границы с низкой непрозрачностью (`rgba(255, 254, 203, 0.08)`).
- Элементы при наведении плавно меняют фон на более светлый тон `#4F4A46` и получают мягкое акцентное свечение.

---

## 8. Готовые примеры компонентов (CSS & HTML)

### 8.1. Карточка датчика умного дома

```html
<div class="shade-sensor-card active">
  <div class="card-header">
    <div class="icon-wrap">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"/>
      </svg>
    </div>
    <span class="status-badge">Климат-контроль</span>
  </div>
  <div class="card-body">
    <div class="device-name">Гостиная</div>
    <div class="metric-value">22.4<span class="unit">°C</span></div>
  </div>
  <div class="card-footer">
    <span class="ai-status">
      <span class="pulse-dot"></span> Локальный контур AI активен
    </span>
  </div>
</div>
```

```css
.shade-sensor-card {
  background: var(--shade-surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--card-radius);
  padding: 20px;
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  color: var(--text-primary);
  transition: all 0.2s ease-in-out;
}

.shade-sensor-card:hover {
  background: var(--shade-surface-3);
  border-color: rgba(254, 168, 47, 0.4);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}

.shade-sensor-card.active .icon-wrap {
  background: rgba(255, 46, 0, 0.15);
  color: var(--accent-secondary);
  border: 1px solid rgba(254, 168, 47, 0.3);
}

.icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--shade-surface-1);
  color: var(--text-secondary);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status-badge {
  font-size: 12px;
  font-weight: 500;
  color: var(--shade-color-orange-base);
  background: rgba(254, 168, 47, 0.12);
  padding: 4px 10px;
  border-radius: 20px;
}

.device-name {
  font-size: 14px;
  color: var(--text-secondary);
}

.metric-value {
  font-family: var(--font-mono);
  font-size: 32px;
  font-weight: 600;
  color: var(--shade-color-cream-base);
}

.metric-value .unit {
  font-size: 18px;
  color: var(--text-muted);
  margin-left: 4px;
}

.card-footer {
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
}

.ai-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--status-success);
  box-shadow: 0 0 8px var(--status-success);
  animation: pulse 2s infinite ease-in-out;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
```

### 8.2. Поле ввода и консоль запросов к AI

```css
.shade-input-group {
  display: flex;
  align-items: center;
  background: var(--shade-surface-1);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 4px 6px 4px 14px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.shade-input-group:focus-within {
  border-color: var(--shade-color-orange-base);
  box-shadow: 0 0 0 3px rgba(254, 168, 47, 0.2);
}

.shade-input-field {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text-primary);
}

.shade-input-field::placeholder {
  color: var(--text-muted);
}
```

---

## 9. Правила «Что можно и чего нельзя» (Do's & Don'ts)

| Раздел | Делать (Do) | Избегать (Don't) |
|--------|-------------|------------------|
| **Цвет** | Использовать `Charcoal Brown` как основу поверхностей, а `Scarlet Fire` точечно для ключевых CTA и акцентов. | Заливать весь экран ярко-алым цветом или использовать стандартный неоновый синий «AI» цвет. |
| **Текст** | Использовать `Cream` (`#FFFECB`) для приятного, тёплого чтения без усталости глаз. | Использовать ослепляющий 100% белый `#FFFFFF` для всех крупных текстовых массивов на тёмном фоне. |
| **Иконки** | Брать лаконичные SVG-иконки из Lucide или Phosphor одинаковой толщины штриха. | Вставлять цветные emoji (💡, 🔒, 🏠) в элементы навигации и карточки. |
| **Шрифты** | Применять `Inter` для UI и `JetBrains Mono` с включённым режимом tabular figures для телеметрии и чисел. | Использовать шрифты с засечками (serif) или декоративные шрифты в интерфейсе умного дома. |
| **Приватность** | Визуально подчёркивать бейджем статус «100% Local / Zero Cloud» на экранах настроек и обработки команд. | Прятать архитектурные особенности конфиденциальности в глубине документации. |

---

## 10. Краткая сводка токенов (Quick Reference Sheet)

```
+------------------+-----------+-------------------------------------------------+
| Название токена  | Значение  | Назначение                                      |
+------------------+-----------+-------------------------------------------------+
| Charcoal Brown   | #423E3B   | Основной тёмный (базовые карточки, плашки)      |
| Scarlet Fire     | #FF2E00   | Главный акцент (кнопки действия, критические UI)|
| Orange           | #FEA82F   | Вторичный акцент (hover, бейджи, перетекание)   |
| Cream            | #FFFECB   | Контрастный светлый текст и мягкий светлый фон  |
| Canvas           | #201E1D   | Глубокий фон приложения                         |
| Font Body        | Inter     | Интерфейс, заголовки, списки, кнопки            |
| Font Mono        | JB Mono   | Числа, логи датчиков, статус, IP, MQTT          |
| Icons            | Lucide    | Штрих 1.75–2.0px, векторный минимализм          |
+------------------+-----------+-------------------------------------------------+
```
