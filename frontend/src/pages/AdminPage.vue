<template>
  <div class="min-h-screen bg-gray-100">
    <div class="bg-white border-b px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button @click="$router.push('/')" class="text-sm text-gray-400 hover:text-gray-600">← Назад</button>
        <h1 class="text-lg font-semibold text-gray-800">{{ SECTIONS.find(x => x.id === activeSection)?.label }}</h1>
      </div>
      <div class="flex items-center gap-4">
        <button
          v-if="auth.user?.role === 'admin'"
          @click="$router.push('/admin/spending')"
          class="text-xs text-brand-700 hover:text-brand-800 font-medium"
        >Расход по направлениям</button>
        <button @click="auth.logout(); $router.push('/login')" class="text-xs text-gray-400 hover:text-gray-600">Выйти</button>
      </div>
    </div>

    <div class="max-w-7xl mx-auto p-6">
      <!-- Section switcher -->
      <div class="flex items-center gap-1 mb-4 bg-white rounded-xl shadow-sm border p-1 w-fit">
        <button
          v-for="sec in SECTIONS" :key="sec.id"
          @click="activeSection = sec.id"
          :class="[
            'px-4 py-2 text-sm font-medium rounded-lg transition-colors',
            activeSection === sec.id
              ? 'bg-brand-600 text-white'
              : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
          ]"
        >{{ sec.label }}</button>
      </div>

      <!-- ===== Scripts section ===== -->
      <div v-if="activeSection === 'scripts'" class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <!-- Type tabs -->
        <div class="border-b flex items-center overflow-x-auto">
          <button
            v-for="tab in tabs" :key="String(tab.id)"
            @click="activeTypeId = tab.id"
            :class="[
              'px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors',
              activeTypeId === tab.id
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            ]"
          >{{ tab.label }}</button>
        </div>

        <!-- Toolbar -->
        <div class="px-4 py-3 flex justify-between items-center border-b bg-gray-50">
          <div class="flex items-center gap-4">
            <span class="text-sm text-gray-500">{{ filteredScripts.length }} скриптов</span>
            <div class="flex items-center gap-2">
              <input
                v-model="scriptSearch"
                type="search"
                placeholder="Поиск по тексту или условию…"
                class="w-64 border rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div class="flex items-center gap-2">
              <label class="text-xs text-gray-400">Тег</label>
              <select
                v-model="activeTag"
                class="border rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
              >
                <option :value="null">Все</option>
                <option value="__none__">Без тега</option>
                <option v-for="tag in existingTags" :key="tag" :value="tag">{{ tag }}</option>
              </select>
            </div>
          </div>
          <button @click="openCreate" class="bg-brand-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-brand-700 font-medium">
            + Создать скрипт
          </button>
        </div>

        <!-- Table -->
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-12">ID</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Условие</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-40">Тег</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-36">Стадия</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-52">Текст фразы</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Активен</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="loading">
                <td colspan="7" class="px-4 py-10 text-center text-gray-400">Загрузка...</td>
              </tr>
              <tr v-else-if="filteredScripts.length === 0">
                <td colspan="7" class="px-4 py-10 text-center text-gray-400">
                  {{ scriptSearch.trim() ? `Ничего не нашлось по «${scriptSearch.trim()}»` : 'Нет скриптов' }}
                </td>
              </tr>
              <tr v-else v-for="s in filteredScripts" :key="s.id" class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3 text-gray-400 font-mono text-xs">{{ s.id }}</td>
                <td class="px-4 py-3 text-gray-800 max-w-sm">
                  <p class="truncate" :title="s.condition">{{ s.condition }}</p>
                  <p
                    v-if="s.follow_up_script_id"
                    class="text-xs text-brand-600 mt-0.5"
                    title="Уйдёт вторым сообщением сразу за этим"
                  >следом → #{{ s.follow_up_script_id }}</p>
                </td>
                <td class="px-4 py-3">
                  <span
                    v-if="s.marketing_tag"
                    class="px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 text-xs font-medium"
                  >{{ s.marketing_tag }}</span>
                  <span v-else class="text-gray-300 text-xs">—</span>
                </td>
                <td class="px-4 py-3">
                  <span
                    v-if="s.funnel_stage"
                    class="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs font-medium"
                    :title="s.funnel_stage"
                  >{{ stageLabel(s.funnel_stage) }}</span>
                  <span v-else class="text-gray-300 text-xs" title="любая стадия">любая</span>
                </td>
                <td class="px-4 py-3 text-gray-500 text-xs max-w-52">
                  <p v-if="s.phrase_text" class="truncate" :title="s.phrase_text">{{ s.phrase_text }}</p>
                  <span v-else class="text-gray-300">—</span>
                </td>
                <td class="px-4 py-3">
                  <button
                    @click="toggleActive(s)"
                    :class="[
                      'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                      s.is_active
                        ? 'bg-green-100 text-green-700 hover:bg-green-200'
                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    ]"
                  >{{ s.is_active ? 'Да' : 'Нет' }}</button>
                </td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openEdit(s)" class="text-brand-700 hover:text-brand-800 text-xs font-medium">Ред.</button>
                    <button @click="confirmDelete(s)" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ===== Ref tags section ===== -->
      <div v-else-if="activeSection === 'ref-tags'" class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <div class="px-4 py-3 flex justify-between items-center border-b bg-gray-50">
          <div class="flex flex-col gap-0.5">
            <span class="text-sm text-gray-500">{{ refTags.length }} меток</span>
            <span class="text-xs text-gray-400">
              Метка из рекламной ссылки: <span class="font-mono text-gray-500">?ref=adb_r&amp;ref_source=<b>rusover449</b></span>
            </span>
          </div>
          <button @click="openRefCreate" class="bg-brand-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-brand-700 font-medium">
            + Добавить метку
          </button>
        </div>

        <!-- Приход без метки — не то же самое, что чужая реклама: ВК присылает
             ref только в первом сообщении, а в группу заходят ещё и из поиска. -->
        <div class="px-4 py-3 border-b flex items-start gap-2 bg-white">
          <input
            type="checkbox"
            id="answer_untagged"
            :checked="answerUntagged"
            @change="saveAnswerUntagged($event.target.checked)"
            class="rounded w-4 h-4 cursor-pointer mt-0.5"
          />
          <label for="answer_untagged" class="text-sm text-gray-700 cursor-pointer">
            Отвечать клиентам без метки
            <span class="block text-xs text-gray-400 mt-0.5">
              Органика: зашли из поиска по группе, по ссылке без параметров, писали раньше.
              Чужая реклама (метка есть, но её нет в списке) блокируется в любом случае.
            </span>
          </label>
          <span v-if="untaggedSaved" class="text-xs text-green-600 ml-auto mt-0.5">сохранено</span>
        </div>

        <!-- Это именно правило для клиентов без ref-метки. Раньше его можно
             было найти и поменять лишь среди всех скриптов. -->
        <div class="px-4 py-4 border-b bg-brand-50/40">
          <div class="flex items-start justify-between gap-4 mb-2">
            <div>
              <h2 class="text-sm font-medium text-gray-800">Общее приветствие</h2>
              <p class="text-xs text-gray-500 mt-0.5">
                Первое сообщение для клиентов без рекламной метки
                <span v-if="defaultGreetingTypeName">· {{ defaultGreetingTypeName }}</span>.
              </p>
            </div>
            <span v-if="defaultGreetingSaved" class="text-xs text-green-600 whitespace-nowrap">сохранено</span>
          </div>
          <div v-if="defaultGreetingLoading" class="text-xs text-gray-400 py-2">Загрузка...</div>
          <p v-else-if="!defaultGreeting" class="text-xs text-amber-700">
            Для этого направления не найдено активное общее приветствие.
          </p>
          <template v-else>
            <textarea
              v-model="defaultGreetingDraft.body"
              rows="4"
              class="w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y bg-white"
              placeholder="Текст приветствия..."
            ></textarea>
            <div class="mt-2">
              <label class="block text-xs text-gray-500 mb-1">Картинки</label>
              <GreetingImages v-model="defaultGreetingDraft.tokens" />
            </div>
            <div class="flex items-center gap-2 mt-2">
              <button
                @click="saveDefaultGreeting"
                :disabled="defaultGreetingSaving || !defaultGreetingChanged"
                class="text-xs px-2.5 py-1 rounded-lg bg-brand-600 text-white disabled:opacity-40 hover:bg-brand-700"
              >{{ defaultGreetingSaving ? 'Сохранение...' : 'Сохранить' }}</button>
              <span v-if="defaultGreetingError" class="text-xs text-red-600">{{ defaultGreetingError }}</span>
            </div>
          </template>
        </div>

        <p v-if="refTags.length === 0" class="px-4 py-3 text-xs text-amber-700 bg-amber-50 border-b">
          Список пуст — ИИ отвечает всем, как и раньше. Как только добавите первую метку,
          он начнёт отвечать только на метки из этого списка, а остальной трафик пойдёт к менеджеру.
        </p>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Метка</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-32">ИИ отвечает</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Первое сообщение</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-44">Заметка</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="refLoading"><td colspan="5" class="px-4 py-10 text-center text-gray-400">Загрузка...</td></tr>
              <tr v-else-if="refTags.length === 0"><td colspan="5" class="px-4 py-10 text-center text-gray-400">Меток пока нет</td></tr>
              <tr v-else v-for="r in refTags" :key="r.id" class="hover:bg-gray-50 transition-colors align-top">
                <td class="px-4 py-3 font-mono text-gray-800">{{ r.tag }}</td>
                <td class="px-4 py-3">
                  <button
                    @click="toggleRefActive(r)"
                    :class="[
                      'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                      r.is_active ? 'bg-green-100 text-green-700 hover:bg-green-200'
                                  : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    ]"
                  >{{ r.is_active ? 'Да' : 'Нет' }}</button>
                </td>
                <td class="px-4 py-3">
                  <select
                    :value="r.greeting_script_id || 0"
                    @change="bindGreeting(r, Number($event.target.value))"
                    class="w-full border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
                  >
                    <option :value="0">— общее приветствие —</option>
                    <option v-for="g in greetingScripts" :key="g.id" :value="g.id">
                      #{{ g.id }} — {{ (g.marketing_tag || g.phrase_text).slice(0, 46) }}
                    </option>
                  </select>
                  <div v-if="greetingDrafts[r.id]" class="mt-1.5">
                    <textarea
                      v-model="greetingDrafts[r.id].body"
                      rows="4"
                      placeholder="Пусто — уйдёт общее приветствие"
                      class="w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
                    ></textarea>
                    <div class="mt-2">
                      <label class="block text-xs text-gray-500 mb-1">Картинки</label>
                      <GreetingImages v-model="greetingDrafts[r.id].tokens" />
                    </div>
                    <div class="flex items-center gap-2 mt-2">
                      <button
                        @click="saveGreetingText(r)"
                        :disabled="!greetingChanged(r)"
                        class="text-xs px-2.5 py-1 rounded-lg bg-brand-600 text-white disabled:opacity-40 hover:bg-brand-700"
                      >Сохранить</button>
                      <span v-if="greetingSaved === r.id" class="text-xs text-green-600">сохранено</span>
                      <span v-else-if="r.greeting_shared_with" class="text-xs text-amber-600">
                        общий ещё с {{ r.greeting_shared_with }} — сохранение сделает свою копию
                      </span>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 text-gray-500 text-xs">{{ r.note || '—' }}</td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openRefEdit(r)" class="text-brand-700 hover:text-brand-800 text-xs font-medium">Ред.</button>
                    <button @click="refDeleteTarget = r" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ===== VK groups section ===== -->
      <div v-else-if="activeSection === 'vk-groups'" class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <div class="px-4 py-3 flex justify-between items-center border-b bg-gray-50">
          <div class="flex flex-col gap-0.5">
            <span class="text-sm text-gray-500">{{ vkGroups.length }} групп</span>
            <span class="text-xs text-gray-400 flex items-center gap-2">
              Адрес вебхука для Callback API:
              <span class="font-mono text-gray-600">{{ webhookUrl }}</span>
              <button
                @click="copyWebhookUrl"
                class="px-1.5 py-0.5 rounded border text-gray-500 hover:bg-gray-100 transition-colors"
              >{{ webhookCopied ? 'скопировано' : 'копировать' }}</button>
            </span>
          </div>
          <button @click="openGroupCreate" class="bg-brand-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-brand-700 font-medium">
            + Добавить группу
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-28">ID группы</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Название</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-40">Токен</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-36">Код подтверждения</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-20">Secret</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-40">Направление</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Активна</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="groupsLoading">
                <td colspan="8" class="px-4 py-10 text-center text-gray-400">Загрузка...</td>
              </tr>
              <tr v-else-if="vkGroups.length === 0">
                <td colspan="8" class="px-4 py-10 text-center text-gray-400">Нет групп</td>
              </tr>
              <tr v-else v-for="g in vkGroups" :key="g.id" class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3 text-gray-700 font-mono text-xs">{{ g.group_id }}</td>
                <td class="px-4 py-3 text-gray-800">{{ g.name }}</td>
                <td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ g.access_token_mask }}</td>
                <!-- ВК выдаёт новый код каждый раз, когда пересоздают сервер
                     Callback API, поэтому правится прямо в строке. -->
                <td class="px-4 py-3">
                  <div class="flex items-center gap-1.5">
                    <input
                      v-model="codeDrafts[g.id]"
                      @keyup.enter="saveConfirmationCode(g)"
                      placeholder="из настроек ВК"
                      class="w-28 border rounded px-1.5 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-brand-500"
                    />
                    <button
                      v-if="codeChanged(g)"
                      @click="saveConfirmationCode(g)"
                      class="text-xs px-2 py-1 rounded bg-brand-600 text-white hover:bg-brand-700"
                    >OK</button>
                    <span v-else-if="codeSaved === g.id" class="text-xs text-green-600">сохранено</span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <span :class="['text-xs font-medium', g.has_secret ? 'text-green-600' : 'text-gray-300']">
                    {{ g.has_secret ? 'да' : 'нет' }}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <span v-if="g.dialog_type_id" class="px-2 py-0.5 rounded-full bg-brand-100 text-brand-700 text-xs font-medium">
                    {{ dialogTypeName(g.dialog_type_id) }}
                  </span>
                  <span v-else class="text-gray-300 text-xs">—</span>
                </td>
                <td class="px-4 py-3">
                  <button
                    @click="toggleGroupActive(g)"
                    :class="[
                      'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                      g.is_active
                        ? 'bg-green-100 text-green-700 hover:bg-green-200'
                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    ]"
                  >{{ g.is_active ? 'Да' : 'Нет' }}</button>
                </td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openGroupEdit(g)" class="text-brand-700 hover:text-brand-800 text-xs font-medium">Ред.</button>
                    <button @click="groupDeleteTarget = g; groupDeleteError = ''" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ===== MAX bots section ===== -->
      <div v-else-if="activeSection === 'max-bots'" class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <div class="px-4 py-3 flex justify-between items-center border-b bg-gray-50">
          <div class="flex flex-col gap-0.5">
            <span class="text-sm text-gray-500">{{ maxBots.length }} ботов</span>
            <span class="text-xs text-gray-400">
              Вставьте токен бота и включите «Активен» — адрес вебхука пропишется в MAX сам.
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button
              @click="loadMaxBots"
              :disabled="maxLoading"
              class="text-sm px-3 py-2 rounded-lg border text-gray-600 hover:bg-gray-100 disabled:opacity-50"
            >{{ maxLoading ? 'Обновление…' : 'Обновить' }}</button>
            <button @click="openMaxCreate" class="bg-brand-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-brand-700 font-medium">
              + Добавить бота
            </button>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Бот</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-32">ID</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-32">Токен</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-44">Вебхук</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-40">Направление</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Активен</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="maxLoading">
                <td colspan="7" class="px-4 py-10 text-center text-gray-400">Загрузка...</td>
              </tr>
              <tr v-else-if="maxBots.length === 0">
                <td colspan="7" class="px-4 py-10 text-center text-gray-400">Ботов нет</td>
              </tr>
              <tr v-else v-for="b in maxBots" :key="b.id" class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3">
                  <div class="text-gray-800">{{ b.name }}</div>
                  <div v-if="b.username" class="text-xs text-gray-400 font-mono">@{{ b.username }}</div>
                </td>
                <td class="px-4 py-3 text-gray-700 font-mono text-xs">{{ b.bot_id }}</td>
                <td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ b.access_token_mask }}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2">
                    <span :class="['text-xs font-medium', b.webhook_subscribed ? 'text-green-600' : 'text-gray-400']">
                      {{ b.webhook_subscribed ? 'подключён' : 'не подключён' }}
                    </span>
                    <button
                      @click="checkMaxBot(b)"
                      :disabled="maxChecking === b.id"
                      class="text-xs px-2 py-0.5 rounded border text-gray-500 hover:bg-gray-100 disabled:opacity-50"
                    >{{ maxChecking === b.id ? '…' : 'Проверить' }}</button>
                  </div>
                  <div v-if="b.webhook_url" class="text-[11px] text-gray-400 font-mono truncate">{{ b.webhook_url }}</div>
                </td>
                <td class="px-4 py-3">
                  <span v-if="b.dialog_type_id" class="px-2 py-0.5 rounded-full bg-brand-100 text-brand-700 text-xs font-medium">
                    {{ dialogTypeName(b.dialog_type_id) }}
                  </span>
                  <span v-else class="text-gray-300 text-xs">—</span>
                </td>
                <td class="px-4 py-3">
                  <!-- Галочка и есть выключатель обработки: она же ставит и снимает
                       подписку на вебхук в MAX. -->
                  <input
                    type="checkbox"
                    :checked="b.is_active"
                    :disabled="maxToggling === b.id"
                    @change="toggleMaxActive(b)"
                    class="rounded w-4 h-4 cursor-pointer disabled:opacity-50"
                  />
                </td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openMaxEdit(b)" class="text-brand-700 hover:text-brand-800 text-xs font-medium">Ред.</button>
                    <button @click="maxDeleteTarget = b; maxDeleteError = ''" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="maxError" class="px-4 py-3 text-xs text-red-500 border-t">{{ maxError }}</p>
      </div>
    </div>

    <!-- Create/Edit MAX bot Modal -->
    <div v-if="showMaxModal" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b flex items-center justify-between sticky top-0 bg-white">
          <h2 class="font-semibold text-gray-800">{{ editMaxBot ? 'Редактировать бота MAX' : 'Добавить бота MAX' }}</h2>
          <button @click="showMaxModal = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Название <span class="text-red-500">*</span></label>
            <input
              v-model="maxForm.name"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              placeholder="Хэмилтон"
            />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">
              Токен бота <span v-if="!editMaxBot" class="text-red-500">*</span>
            </label>
            <input
              v-model="maxForm.access_token"
              class="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              :placeholder="editMaxBot ? 'оставить текущий' : 'токен из настроек бота в MAX'"
            />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Направление</label>
            <select v-model="maxForm.dialog_type_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="null">— не задано —</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>
          <div class="flex items-center gap-2">
            <input type="checkbox" v-model="maxForm.is_active" id="max_is_active" class="rounded w-4 h-4 cursor-pointer" />
            <label for="max_is_active" class="text-sm text-gray-700 cursor-pointer">Активен — включить обработку сообщений</label>
          </div>
          <p class="text-xs text-gray-400">
            Адрес вебхука прописывается в MAX автоматически при включении, вручную ничего
            настраивать не нужно. ID и @username бота подтянутся из MAX по токену.
          </p>
          <p v-if="maxFormError" class="text-xs text-red-500">{{ maxFormError }}</p>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2 sticky bottom-0 bg-white">
          <button @click="showMaxModal = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="saveMaxBot"
            :disabled="maxSaving || !canSaveMaxBot"
            class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {{ maxSaving ? 'Сохранение...' : (editMaxBot ? 'Сохранить' : 'Добавить') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete MAX bot confirm -->
    <div v-if="maxDeleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h3 class="font-semibold text-gray-800 mb-2">Удалить бота?</h3>
        <p class="text-sm text-gray-600 mb-4">
          «{{ maxDeleteTarget.name }}» будет отключён от системы.
        </p>
        <p v-if="maxDeleteError" class="text-xs text-red-500 mb-3">{{ maxDeleteError }}</p>
        <div class="flex justify-end gap-2">
          <button @click="maxDeleteTarget = null" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="doDeleteMaxBot"
            :disabled="maxSaving"
            class="px-4 py-2 text-sm bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50"
          >Удалить</button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Script Modal -->
    <div v-if="showModal" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b flex items-center justify-between sticky top-0 bg-white">
          <h2 class="font-semibold text-gray-800">{{ editScript ? 'Редактировать скрипт' : 'Создать скрипт' }}</h2>
          <button @click="showModal = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Тип</label>
            <select v-model="form.type_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="null">— не задан —</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Условие</label>
            <textarea
              v-model="form.condition"
              rows="6"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
              placeholder="Текст условия..."
            ></textarea>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Текст фразы <span class="text-red-500">*</span></label>
            <textarea
              v-model="form.phrase_text"
              rows="4"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
              placeholder="Текст, который отправится клиенту..."
            ></textarea>
            <p class="text-xs text-gray-400 mt-1">Поддерживается spintax: {вариант1|вариант2} — выбирается случайный вариант.</p>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Картинки</label>
            <GreetingImages v-model="form.tokens" />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Маркетинговый тег</label>
            <input
              v-model="form.marketing_tag"
              list="known-ref-tags"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              placeholder="Без # — пусто = для всех клиентов"
            />
            <datalist id="known-ref-tags">
              <option v-for="r in refTags" :key="r.id" :value="r.tag" />
            </datalist>
            <p v-if="unknownTags.length" class="text-xs text-amber-700 mt-1">
              Таких реф-меток нет: {{ unknownTags.join(', ') }}. Скрипт не увидит ни один
              клиент — метка должна совпадать с той, что в рекламной ссылке.
            </p>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Стадия воронки</label>
            <select v-model="form.funnel_stage" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option value="">— любая (показывать всегда) —</option>
              <option v-for="st in FUNNEL_STAGES" :key="st.value" :value="st.value">{{ st.label }}</option>
            </select>
            <p class="text-xs text-gray-400 mt-1">Скрипт виден, пока диалог не прошёл эту стадию. «Любая» — без ограничения.</p>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Заменяет шаг</label>
            <select v-model="form.variant_of_script_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="0">— ничего не заменяет —</option>
              <option v-for="s in followUpOptions" :key="s.id" :value="s.id">
                #{{ s.id }} — {{ s.condition.slice(0, 70) }}
              </option>
            </select>
            <p class="text-xs text-gray-400 mt-1">
              Уйдёт вместо выбранного шага клиентам с меткой этого скрипта. Так делают
              свой расчёт под метку: обычный остаётся для всех остальных.
            </p>
            <label v-if="form.variant_of_script_id" class="flex items-start gap-2 mt-2 text-sm">
              <input type="checkbox" v-model="form.is_pair_variant" class="mt-0.5" />
              <span>
                Вариант для заказа на двоих
                <span class="block text-xs text-gray-400">
                  Уйдёт вместо выбранного шага, когда клиент назвал две надписи или
                  сказал, что изделий два. Метка при этом не нужна.
                </span>
              </span>
            </label>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Отправить следом</label>
            <select v-model="form.follow_up_script_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="0">— ничего —</option>
              <option v-for="s in followUpOptions" :key="s.id" :value="s.id">
                #{{ s.id }} — {{ s.condition.slice(0, 70) }}
              </option>
            </select>
            <p class="text-xs text-gray-400 mt-1">Уйдёт вторым сообщением сразу за этим, не дожидаясь ответа клиента.</p>
          </div>
          <div v-if="editScript" class="flex items-center gap-2">
            <input type="checkbox" v-model="form.is_active" id="modal_is_active" class="rounded w-4 h-4 cursor-pointer" />
            <label for="modal_is_active" class="text-sm text-gray-700 cursor-pointer">Активен</label>
          </div>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2 sticky bottom-0 bg-white">
          <button @click="showModal = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="saveScript"
            :disabled="saving || !form.condition.trim() || (!form.phrase_text.trim() && !form.tokens.length)"
            class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {{ saving ? 'Сохранение...' : (editScript ? 'Сохранить' : 'Создать') }}
          </button>
        </div>
      </div>
    </div>


    <!-- Ref tag modal -->
    <div v-if="showRefModal" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div class="px-6 py-4 border-b">
          <h2 class="font-semibold text-gray-800">{{ editRefTag ? 'Метка #' + editRefTag.id : 'Новая реф-метка' }}</h2>
        </div>
        <div class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Метка</label>
            <input
              v-model="refForm.tag"
              placeholder="rusover449"
              class="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <p class="text-xs text-gray-400 mt-1">Значение <span class="font-mono">ref_source</span> из рекламной ссылки.</p>
          </div>
          <div v-if="!editRefTag">
            <label class="block text-xs text-gray-500 mb-1.5">Направление</label>
            <select v-model="refForm.type_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="null">— не задано —</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Первое сообщение</label>
            <textarea
              v-model="refForm.greeting.body"
              rows="5"
              placeholder="Оставьте пустым — уйдёт общее приветствие"
              class="w-full border rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
            ></textarea>
            <p class="text-xs text-gray-400 mt-1">
              Текст, который клиент с этой метки получит первым. Имя —
              <span class="font-mono">[Имя]</span>.
            </p>
            <div class="mt-3">
              <label class="block text-xs text-gray-500 mb-1.5">Картинки приветствия</label>
              <GreetingImages v-model="refForm.greeting.tokens" />
            </div>
            <p v-if="editRefTag && editRefTag.greeting_shared_with" class="text-xs text-amber-600 mt-1">
              Этот текст сейчас общий ещё с {{ editRefTag.greeting_shared_with }} меткой(ами) —
              при сохранении метка получит свою копию, остальные не изменятся.
            </p>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Заметка</label>
            <input
              v-model="refForm.note"
              placeholder="Например: свитшоты, гербы, август"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div class="flex items-center gap-2">
            <input type="checkbox" v-model="refForm.is_active" id="ref_is_active" class="rounded w-4 h-4 cursor-pointer" />
            <label for="ref_is_active" class="text-sm text-gray-700 cursor-pointer">ИИ отвечает на эту метку</label>
          </div>
          <p v-if="refError" class="text-red-500 text-sm">{{ refError }}</p>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2">
          <button @click="showRefModal = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="saveRefTag"
            :disabled="refSaving || !refForm.tag.trim()"
            class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >{{ refSaving ? 'Сохранение...' : (editRefTag ? 'Сохранить' : 'Создать') }}</button>
        </div>
      </div>
    </div>

    <!-- Ref tag delete confirmation -->
    <div v-if="refDeleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-2">Удалить метку «{{ refDeleteTarget.tag }}»?</h2>
        <p class="text-sm text-gray-500 mb-6">Клиенты с этой метки перестанут получать ответы ИИ.</p>
        <div class="flex gap-2">
          <button @click="refDeleteTarget = null" class="flex-1 px-4 py-2 text-sm border rounded-lg hover:bg-gray-50">Отмена</button>
          <button @click="doRefDelete" class="flex-1 px-4 py-2 text-sm bg-red-500 text-white rounded-lg hover:bg-red-600">Удалить</button>
        </div>
      </div>
    </div>

    <!-- Delete script confirmation -->
    <div v-if="deleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-2">Удалить скрипт #{{ deleteTarget.id }}?</h2>
        <p class="text-sm text-gray-500 mb-6 line-clamp-2">{{ deleteTarget.condition }}</p>
        <div class="flex justify-end gap-2">
          <button @click="deleteTarget = null" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="doDelete"
            :disabled="saving"
            class="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
          >
            {{ saving ? '...' : 'Удалить' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Create/Edit VK group Modal -->
    <div v-if="showGroupModal" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b flex items-center justify-between sticky top-0 bg-white">
          <h2 class="font-semibold text-gray-800">{{ editGroup ? 'Редактировать группу' : 'Добавить группу' }}</h2>
          <button @click="showGroupModal = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">ID группы <span class="text-red-500">*</span></label>
              <input
                v-model.number="groupForm.group_id"
                type="number"
                :disabled="!!editGroup"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-100 disabled:text-gray-400"
                placeholder="123456789"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Название <span class="text-red-500">*</span></label>
              <input
                v-model="groupForm.name"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                placeholder="Моё сообщество"
              />
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">
              Токен доступа <span v-if="!editGroup" class="text-red-500">*</span>
            </label>
            <input
              v-model="groupForm.access_token"
              class="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              :placeholder="editGroup ? 'оставить текущий' : 'vk1.a....'"
            />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Код подтверждения <span class="text-red-500">*</span></label>
              <input
                v-model="groupForm.confirmation_code"
                class="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                placeholder="a1b2c3d4"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Секретный ключ <span class="text-gray-400">(необязательно)</span></label>
              <input
                v-model="groupForm.secret_key"
                class="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                :placeholder="editGroup?.has_secret ? 'оставить текущий' : 'secret'"
              />
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Направление</label>
            <select v-model="groupForm.dialog_type_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white">
              <option :value="null">— не задано —</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>
          <div v-if="editGroup" class="flex items-center gap-2">
            <input type="checkbox" v-model="groupForm.is_active" id="group_is_active" class="rounded w-4 h-4 cursor-pointer" />
            <label for="group_is_active" class="text-sm text-gray-700 cursor-pointer">Активна</label>
          </div>
          <p class="text-xs text-gray-400">
            В настройках Callback API сообщества укажите адрес вебхука
            <span class="font-mono text-gray-500">https://&lt;домен&gt;/webhook/vk</span>
            и этот код подтверждения.
          </p>
          <p v-if="groupError" class="text-xs text-red-500">{{ groupError }}</p>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2 sticky bottom-0 bg-white">
          <button @click="showGroupModal = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="saveGroup"
            :disabled="groupSaving || !canSaveGroup"
            class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {{ groupSaving ? 'Сохранение...' : (editGroup ? 'Сохранить' : 'Добавить') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete VK group confirmation -->
    <div v-if="groupDeleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-2">Удалить группу «{{ groupDeleteTarget.name }}»?</h2>
        <p class="text-sm text-gray-500 mb-4">ID группы: {{ groupDeleteTarget.group_id }}. Вебхуки от неё перестанут обрабатываться.</p>
        <p v-if="groupDeleteError" class="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2 mb-4">
          {{ groupDeleteError }}
        </p>
        <div class="flex justify-end gap-2">
          <button @click="groupDeleteTarget = null" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="doDeleteGroup"
            :disabled="groupSaving"
            class="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
          >
            {{ groupSaving ? '...' : 'Удалить' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'
import GreetingImages from '../components/GreetingImages.vue'
import { splitAttachments, joinAttachments } from '../utils/attachments'

const auth = useAuthStore()

const SECTIONS = [
  { id: 'scripts', label: 'Скрипты' },
  { id: 'ref-tags', label: 'Реф-метки' },
  { id: 'vk-groups', label: 'Группы ВК' },
  { id: 'max-bots', label: 'Боты MAX' },
]
const activeSection = ref('scripts')

const loading = ref(false)
const saving = ref(false)
const dialogTypes = ref([])
const scripts = ref([])
const activeTypeId = ref(null)
const activeTag = ref(null)

const showModal = ref(false)
const editScript = ref(null)
const deleteTarget = ref(null)

const form = ref({ type_id: null, condition: '', phrase_text: '', tokens: [], marketing_tag: '', funnel_stage: '', follow_up_script_id: 0, variant_of_script_id: 0, is_pair_variant: false, is_active: true })

// Метка скрипта должна совпадать с реф-меткой из рекламной ссылки. В поле
// писали человеческое название — «свитшот + жилет, 8980р», — и такой скрипт не
// доставался никому: запятая делит его на две метки, которых нет ни у кого.
const unknownTags = computed(() => {
  const known = new Set(refTags.value.map(r => (r.tag || '').trim().toUpperCase()))
  return (form.value.marketing_tag || '')
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)
    .filter(t => !known.has(t.replace(/^#/, '').toUpperCase()))
})

// Funnel steps (must mirror STAGES in app/ai/funnel_agent.py). Empty = любая стадия (always shown).
const FUNNEL_STAGES = [
  { value: 'greeting', label: 'greeting — приветствие' },
  { value: 'format', label: 'format — выбор формата' },
  { value: 'calculation', label: 'calculation — расчёт цены' },
  { value: 'timing', label: 'timing — сроки' },
  { value: 'photo', label: 'photo — фото' },
  { value: 'contacts', label: 'contacts — имя+телефон' },
  { value: 'prepayment', label: 'prepayment — предоплата' },
  { value: 'paid', label: 'paid — оплачено' },
]
const stageLabel = (v) => FUNNEL_STAGES.find(s => s.value === v)?.label.split(' — ')[1] || v

const tabs = computed(() => [
  { id: null, label: 'Все' },
  ...dialogTypes.value.map(t => ({ id: t.id, label: t.display_name })),
])

const scriptSearch = ref('')

const existingTags = computed(() =>
  [...new Set(scripts.value.map(s => s.marketing_tag).filter(Boolean))].sort()
)

// Кандидаты в связку: тот же тип диалога, и не сам скрипт (на себя ссылаться нельзя).
const followUpOptions = computed(() =>
  scripts.value.filter(s =>
    s.id !== editScript.value?.id &&
    (form.value.type_id === null || s.type_id === form.value.type_id)
  )
)

const filteredScripts = computed(() => {
  let base = scripts.value
  if (activeTypeId.value !== null) base = base.filter(s => s.type_id === activeTypeId.value)
  if (activeTag.value === '__none__') base = base.filter(s => !s.marketing_tag)
  else if (activeTag.value !== null) base = base.filter(s => s.marketing_tag === activeTag.value)
  // Пятьсот с лишним скриптов, и почти все с одинаковым началом условия — найти
  // нужный, листая таблицу, нельзя. Ищем и по тексту фразы: расчёт узнают по
  // «5 990», а не по названию условия.
  const q = scriptSearch.value.trim().toLowerCase()
  if (q) {
    base = base.filter(s =>
      (s.phrase_text || '').toLowerCase().includes(q)
      || (s.condition || '').toLowerCase().includes(q)
      || (s.marketing_tag || '').toLowerCase().includes(q)
      || String(s.id) === q
    )
  }
  return base
})

async function load() {
  loading.value = true
  try {
    const [typesRes, scriptsRes] = await Promise.all([
      api.get('/dialog-types/'),
      api.get('/scripts/', { params: { include_inactive: true } }),
    ])
    dialogTypes.value = typesRes.data
    scripts.value = scriptsRes.data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editScript.value = null
  form.value = { type_id: activeTypeId.value, condition: '', phrase_text: '', tokens: [], marketing_tag: '', funnel_stage: '', follow_up_script_id: 0, variant_of_script_id: 0, is_pair_variant: false, is_active: true }
  showModal.value = true
}

function openEdit(s) {
  editScript.value = s
  // Картинки правятся блоком ниже, а не ссылками посреди текста: в расчёте их
  // три штуки по триста символов, и добраться до самого текста было нельзя.
  const { body, tokens } = splitGreeting(s.phrase_text)
  form.value = { type_id: s.type_id, condition: s.condition, phrase_text: body, tokens, marketing_tag: s.marketing_tag || '', funnel_stage: s.funnel_stage || '', follow_up_script_id: s.follow_up_script_id || 0, variant_of_script_id: s.variant_of_script_id || 0, is_pair_variant: !!s.is_pair_variant, is_active: s.is_active }
  showModal.value = true
}

async function saveScript() {
  saving.value = true
  try {
    const marketing_tag = form.value.marketing_tag?.trim() || ''
    const funnel_stage = form.value.funnel_stage || ''
    // 0, а не null: PATCH на бэке режет null-поля (exclude_none), поэтому «связки
    // нет» приходит нулём и там же превращается обратно в NULL.
    const follow_up_script_id = form.value.follow_up_script_id || 0
    const variant_of_script_id = form.value.variant_of_script_id || 0
    // Флаг живёт только вместе с заменой шага: без неё заменять нечего.
    const is_pair_variant = !!variant_of_script_id && !!form.value.is_pair_variant
    const phrase_text = joinGreeting({ body: form.value.phrase_text, tokens: form.value.tokens })
    if (editScript.value) {
      const { tokens: _tokens, ...rest } = form.value
      const res = await api.patch(`/scripts/${editScript.value.id}`, { ...rest, phrase_text, marketing_tag, funnel_stage, follow_up_script_id, variant_of_script_id, is_pair_variant })
      const idx = scripts.value.findIndex(s => s.id === editScript.value.id)
      if (idx !== -1) scripts.value[idx] = res.data
    } else {
      const res = await api.post('/scripts/', {
        condition: form.value.condition,
        phrase_text,
        type_id: form.value.type_id,
        marketing_tag,
        funnel_stage,
        follow_up_script_id,
        variant_of_script_id,
        is_pair_variant,
      })
      scripts.value.push(res.data)
    }
    showModal.value = false
  } finally {
    saving.value = false
  }
}

async function toggleActive(s) {
  const res = await api.patch(`/scripts/${s.id}`, { is_active: !s.is_active })
  const idx = scripts.value.findIndex(x => x.id === s.id)
  if (idx !== -1) scripts.value[idx] = res.data
}

function confirmDelete(s) {
  deleteTarget.value = s
}

async function doDelete() {
  saving.value = true
  try {
    await api.delete(`/scripts/${deleteTarget.value.id}`)
    scripts.value = scripts.value.filter(s => s.id !== deleteTarget.value.id)
    deleteTarget.value = null
  } finally {
    saving.value = false
  }
}

// ===== Группы ВК =====


// ===== Реф-метки =====
// Заказчик: «метки проставляют и редактируют постоянно + редактирование первых
// сообщений» — поэтому текст приветствия правится прямо в строке метки, а не
// поиском нужного скрипта среди сотни остальных.
const refTags = ref([])
const refLoading = ref(false)
const refSaving = ref(false)
const showRefModal = ref(false)
const editRefTag = ref(null)
const refDeleteTarget = ref(null)
const refError = ref('')
const refForm = ref({ tag: '', type_id: null, is_active: true, note: '', greeting: { body: '', tokens: [] } })

// Черновики текстов приветствий: правим у себя, сохраняем по кнопке.
// Каждый — { body, tokens }: текст без вложений и список токенов вложений.
// В базе они лежат одной строкой, но править ссылки руками среди текста —
// то, из-за чего картинки в приветствии и не менялись.
const greetingDrafts = ref({})
const greetingSaved = ref(null)

const defaultGreeting = ref(null)
const defaultGreetingDraft = ref({ body: '', tokens: [] })
const defaultGreetingLoading = ref(false)
const defaultGreetingSaving = ref(false)
const defaultGreetingSaved = ref(false)
const defaultGreetingError = ref('')

const splitGreeting = splitAttachments
const joinGreeting = joinAttachments

const greetingScripts = computed(() =>
  scripts.value.filter(s => (s.condition || '').toLowerCase().includes('первое приветственное'))
)

// На вкладке «Все» показываем настройку первого направления — это тот же выбор,
// который используется при создании новой реф-метки.
const defaultGreetingTypeId = computed(() => activeTypeId.value ?? dialogTypes.value[0]?.id ?? null)
const defaultGreetingTypeName = computed(() =>
  dialogTypes.value.find(t => t.id === defaultGreetingTypeId.value)?.display_name || ''
)
const defaultGreetingChanged = computed(() =>
  defaultGreeting.value !== null
  && joinGreeting(defaultGreetingDraft.value) !== joinGreeting(splitGreeting(defaultGreeting.value.phrase_text))
)

async function loadDefaultGreeting() {
  defaultGreetingLoading.value = true
  defaultGreetingError.value = ''
  try {
    const res = await api.get('/scripts/default-greeting', {
      params: defaultGreetingTypeId.value === null ? {} : { type_id: defaultGreetingTypeId.value },
    })
    defaultGreeting.value = res.data
    defaultGreetingDraft.value = splitGreeting(res.data?.phrase_text || '')
  } catch (e) {
    defaultGreeting.value = null
    defaultGreetingError.value = e.response?.data?.detail || 'Не удалось загрузить приветствие'
  } finally {
    defaultGreetingLoading.value = false
  }
}

async function saveDefaultGreeting() {
  if (!defaultGreeting.value) return
  defaultGreetingSaving.value = true
  defaultGreetingError.value = ''
  try {
    const res = await api.patch(`/scripts/${defaultGreeting.value.id}`, {
      phrase_text: joinGreeting(defaultGreetingDraft.value),
    })
    defaultGreeting.value = res.data
    defaultGreetingDraft.value = splitGreeting(res.data.phrase_text)
    const index = scripts.value.findIndex(s => s.id === res.data.id)
    if (index !== -1) scripts.value[index] = res.data
    defaultGreetingSaved.value = true
    setTimeout(() => { defaultGreetingSaved.value = false }, 2000)
  } catch (e) {
    defaultGreetingError.value = e.response?.data?.detail || 'Не удалось сохранить приветствие'
  } finally {
    defaultGreetingSaving.value = false
  }
}

watch(defaultGreetingTypeId, () => {
  // Переключение направления в «Скриптах» сразу переключает и общее
  // приветствие: не приходится искать его в таблице вручную.
  if (dialogTypes.value.length) loadDefaultGreeting()
})

// Черновик привязан к МЕТКЕ, а не к скрипту: один и тот же скрипт может стоять у
// нескольких меток, и правка «под одну» не должна их путать между собой.
function syncGreetingDrafts() {
  for (const r of refTags.value) greetingDrafts.value[r.id] = splitGreeting(r.greeting_text)
}

// Сравниваем собранный текст с собранным же: в исходном токены могут стоять с
// другими отбивками, и «изменено» загоралось бы сразу после загрузки.
const greetingChanged = (r) =>
  greetingDrafts.value[r.id] !== undefined
  && joinGreeting(greetingDrafts.value[r.id]) !== joinGreeting(splitGreeting(r.greeting_text))


// Галка живёт на направлении: у каждого своя реклама и свой органический трафик.
const untaggedSaved = ref(false)
const answerUntagged = computed(() => {
  const t = dialogTypes.value.find(x => x.id === (activeTypeId.value ?? dialogTypes.value[0]?.id))
  return t ? t.answer_untagged !== false : true
})

async function saveAnswerUntagged(value) {
  const t = dialogTypes.value.find(x => x.id === (activeTypeId.value ?? dialogTypes.value[0]?.id))
  if (!t) return
  const res = await api.patch(`/dialog-types/${t.id}`, { answer_untagged: value })
  t.answer_untagged = res.data.answer_untagged
  untaggedSaved.value = true
  setTimeout(() => { untaggedSaved.value = false }, 2000)
}

async function loadRefTags() {
  refLoading.value = true
  try {
    const res = await api.get('/ref-tags/')
    refTags.value = res.data
    syncGreetingDrafts()
  } finally {
    refLoading.value = false
  }
}

function openRefCreate() {
  editRefTag.value = null
  refError.value = ''
  // Со вкладки «все направления» activeTypeId пуст, и метка создавалась без
  // направления — по умолчанию подставляем первое, как в приветствии ниже.
  refForm.value = {
    tag: '', type_id: activeTypeId.value ?? dialogTypes.value[0]?.id ?? null,
    is_active: true, note: '', greeting: splitGreeting(''),
  }
  showRefModal.value = true
}

function openRefEdit(r) {
  editRefTag.value = r
  refError.value = ''
  refForm.value = {
    tag: r.tag, type_id: r.type_id, is_active: r.is_active,
    note: r.note || '', greeting: splitGreeting(r.greeting_text),
  }
  showRefModal.value = true
}

async function saveRefTag() {
  refSaving.value = true
  refError.value = ''
  try {
    if (editRefTag.value) {
      await applyRefTag(await api.patch(`/ref-tags/${editRefTag.value.id}`, {
        tag: refForm.value.tag, is_active: refForm.value.is_active,
        note: refForm.value.note, greeting_text: joinGreeting(refForm.value.greeting),
      }))
    } else {
      const { greeting, ...fields } = refForm.value
      const res = await api.post('/ref-tags/', {
        ...fields, greeting_text: joinGreeting(greeting),
      })
      refTags.value.push(res.data)
      greetingDrafts.value[res.data.id] = splitGreeting(res.data.greeting_text)
      await ensureScriptLoaded(res.data.greeting_script_id)
    }
    showRefModal.value = false
  } catch (e) {
    refError.value = e.response?.data?.detail || 'Ошибка'
  } finally {
    refSaving.value = false
  }
}

async function toggleRefActive(r) {
  const res = await api.patch(`/ref-tags/${r.id}`, { is_active: !r.is_active })
  r.is_active = res.data.is_active
}

async function applyRefTag(res) {
  const i = refTags.value.findIndex(x => x.id === res.data.id)
  if (i !== -1) refTags.value[i] = res.data
  greetingDrafts.value[res.data.id] = splitGreeting(res.data.greeting_text)
  // Метке могли завести собственное приветствие — без перечитывания списка
  // выпадашка не найдёт его среди вариантов и покажется пустой.
  await ensureScriptLoaded(res.data.greeting_script_id)
}

async function ensureScriptLoaded(scriptId) {
  if (!scriptId || scripts.value.some(s => s.id === scriptId)) return
  const res = await api.get('/scripts/', { params: { include_inactive: true } })
  scripts.value = res.data
}

async function bindGreeting(r, scriptId) {
  // 0 вместо null: PATCH на бэке режет null-поля (exclude_none).
  await applyRefTag(await api.patch(`/ref-tags/${r.id}`, { greeting_script_id: scriptId }))
}

// Сохраняем через метку, а не через скрипт: бэк сам решит, править текст на месте
// или завести метке свою копию, если этим приветствием пишут и другие метки.
async function saveGreetingText(r) {
  await applyRefTag(await api.patch(`/ref-tags/${r.id}`, {
    greeting_text: joinGreeting(greetingDrafts.value[r.id]),
  }))
  greetingSaved.value = r.id
  setTimeout(() => { if (greetingSaved.value === r.id) greetingSaved.value = null }, 2000)
}

async function doRefDelete() {
  await api.delete(`/ref-tags/${refDeleteTarget.value.id}`)
  refTags.value = refTags.value.filter(x => x.id !== refDeleteTarget.value.id)
  refDeleteTarget.value = null
}

const groupsLoading = ref(false)
const groupSaving = ref(false)
const vkGroups = ref([])
const showGroupModal = ref(false)
const editGroup = ref(null)
const groupDeleteTarget = ref(null)
const groupDeleteError = ref('')
const groupError = ref('')

const groupForm = ref({ group_id: null, name: '', access_token: '', confirmation_code: '', secret_key: '', dialog_type_id: null, is_active: true })

// Адрес вебхука — это тот же домен, с которого открыта панель: nginx отдаёт и
// её, и /webhook/vk. Берём из адресной строки, чтобы он не расходился с
// реальностью при переезде и его не приходилось спрашивать у разработчика.
const webhookUrl = computed(() => `${window.location.origin}/webhook/vk`)
const webhookCopied = ref(false)

async function copyWebhookUrl() {
  await navigator.clipboard.writeText(webhookUrl.value)
  webhookCopied.value = true
  setTimeout(() => { webhookCopied.value = false }, 2000)
}

// Код подтверждения меняется каждый раз, когда в ВК пересоздают сервер Callback
// API, — правим его прямо в строке, не открывая форму со всеми полями.
const codeDrafts = ref({})
const codeSaved = ref(null)

const codeChanged = (g) =>
  codeDrafts.value[g.id] !== undefined && codeDrafts.value[g.id].trim() !== g.confirmation_code

async function saveConfirmationCode(g) {
  const code = (codeDrafts.value[g.id] || '').trim()
  if (!code || code === g.confirmation_code) return
  const res = await api.patch(`/vk-groups/${g.id}`, { confirmation_code: code })
  const i = vkGroups.value.findIndex(x => x.id === g.id)
  if (i !== -1) vkGroups.value[i] = res.data
  codeDrafts.value[g.id] = res.data.confirmation_code
  codeSaved.value = g.id
  setTimeout(() => { if (codeSaved.value === g.id) codeSaved.value = null }, 2000)
}

const dialogTypeName = (id) => dialogTypes.value.find(t => t.id === id)?.display_name || `#${id}`

const canSaveGroup = computed(() => {
  const f = groupForm.value
  if (!f.name.trim() || !f.confirmation_code.trim()) return false
  if (!editGroup.value && (!f.group_id || !f.access_token.trim())) return false
  return true
})

async function loadGroups() {
  groupsLoading.value = true
  try {
    const res = await api.get('/vk-groups/')
    vkGroups.value = res.data
    for (const g of vkGroups.value) codeDrafts.value[g.id] = g.confirmation_code
  } finally {
    groupsLoading.value = false
  }
}

function openGroupCreate() {
  editGroup.value = null
  groupError.value = ''
  groupForm.value = { group_id: null, name: '', access_token: '', confirmation_code: '', secret_key: '', dialog_type_id: null, is_active: true }
  showGroupModal.value = true
}

function openGroupEdit(g) {
  editGroup.value = g
  groupError.value = ''
  // Токен и секрет не возвращаются с бэка — пустое поле означает «не менять».
  groupForm.value = {
    group_id: g.group_id,
    name: g.name,
    access_token: '',
    confirmation_code: g.confirmation_code,
    secret_key: '',
    dialog_type_id: g.dialog_type_id ?? null,
    is_active: g.is_active,
  }
  showGroupModal.value = true
}

async function saveGroup() {
  groupSaving.value = true
  groupError.value = ''
  try {
    const f = groupForm.value
    if (editGroup.value) {
      const payload = {
        name: f.name.trim(),
        access_token: f.access_token.trim(),
        confirmation_code: f.confirmation_code.trim(),
        dialog_type_id: f.dialog_type_id,
        is_active: f.is_active,
      }
      if (f.secret_key.trim()) payload.secret_key = f.secret_key.trim()
      const res = await api.patch(`/vk-groups/${editGroup.value.id}`, payload)
      const idx = vkGroups.value.findIndex(g => g.id === editGroup.value.id)
      if (idx !== -1) vkGroups.value[idx] = res.data
    } else {
      const payload = {
        group_id: f.group_id,
        name: f.name.trim(),
        access_token: f.access_token.trim(),
        confirmation_code: f.confirmation_code.trim(),
        dialog_type_id: f.dialog_type_id,
      }
      if (f.secret_key.trim()) payload.secret_key = f.secret_key.trim()
      const res = await api.post('/vk-groups/', payload)
      vkGroups.value.push(res.data)
    }
    showGroupModal.value = false
  } catch (e) {
    groupError.value = e.response?.data?.detail || 'Ошибка сохранения'
  } finally {
    groupSaving.value = false
  }
}

async function toggleGroupActive(g) {
  const res = await api.patch(`/vk-groups/${g.id}`, { is_active: !g.is_active })
  const idx = vkGroups.value.findIndex(x => x.id === g.id)
  if (idx !== -1) vkGroups.value[idx] = res.data
}

async function doDeleteGroup() {
  groupSaving.value = true
  groupDeleteError.value = ''
  try {
    await api.delete(`/vk-groups/${groupDeleteTarget.value.id}`)
    vkGroups.value = vkGroups.value.filter(g => g.id !== groupDeleteTarget.value.id)
    groupDeleteTarget.value = null
  } catch (e) {
    // Группу с перепиской бэк удалить не даст — раньше отказ пропадал молча,
    // и окно просто «не закрывалось».
    groupDeleteError.value = e.response?.data?.detail || 'Не удалось удалить группу'
  } finally {
    groupSaving.value = false
  }
}

// ===== Боты MAX =====
// Подключение бота — одна операция: вставить токен и включить галочку. Всё
// остальное (ID бота, @username, адрес вебхука и подписка на него в MAX)
// делает бэк, поэтому в форме этих полей нет.
const maxBots = ref([])
const maxLoading = ref(false)
const maxSaving = ref(false)
const showMaxModal = ref(false)
const editMaxBot = ref(null)
const maxDeleteTarget = ref(null)
const maxDeleteError = ref('')
const maxFormError = ref('')
const maxError = ref('')
const maxToggling = ref(null)
const maxChecking = ref(null)

const maxForm = ref({ name: '', access_token: '', dialog_type_id: null, is_active: true })

const canSaveMaxBot = computed(() => {
  const f = maxForm.value
  if (!f.name.trim()) return false
  if (!editMaxBot.value && !f.access_token.trim()) return false
  return true
})

async function loadMaxBots() {
  maxLoading.value = true
  maxError.value = ''
  try {
    const res = await api.get('/max-bots/')
    maxBots.value = res.data
  } catch (e) {
    // Раньше ошибка запроса оставляла пустой массив, и админ видел «Ботов нет»,
    // хотя добавленные записи никуда не делись. Показываем причину и не даём
    // принять недоступный API за пустой список.
    maxBots.value = []
    maxError.value = e.response?.data?.detail || 'Не удалось загрузить список ботов. Попробуйте обновить страницу.'
  } finally {
    maxLoading.value = false
  }
}

function openMaxCreate() {
  editMaxBot.value = null
  maxFormError.value = ''
  maxForm.value = { name: '', access_token: '', dialog_type_id: null, is_active: true }
  showMaxModal.value = true
}

function openMaxEdit(b) {
  editMaxBot.value = b
  maxFormError.value = ''
  // Токен наружу не отдаётся — пустое поле означает «не менять».
  maxForm.value = {
    name: b.name,
    access_token: '',
    dialog_type_id: b.dialog_type_id ?? null,
    is_active: b.is_active,
  }
  showMaxModal.value = true
}

function replaceMaxBot(bot) {
  const i = maxBots.value.findIndex(x => x.id === bot.id)
  if (i !== -1) maxBots.value[i] = bot
  else maxBots.value.push(bot)
}

async function saveMaxBot() {
  maxSaving.value = true
  maxFormError.value = ''
  try {
    const f = maxForm.value
    const payload = {
      name: f.name.trim(),
      dialog_type_id: f.dialog_type_id,
      is_active: f.is_active,
    }
    if (f.access_token.trim()) payload.access_token = f.access_token.trim()
    if (editMaxBot.value) {
      const res = await api.patch(`/max-bots/${editMaxBot.value.id}`, payload)
      replaceMaxBot(res.data)
    } else {
      await api.post('/max-bots/', payload)
      // Берём итоговый список из БД, а не полагаемся на локальный push: так
      // новая строка сразу оказывается в том же порядке и состоянии, что и
      // после обновления страницы.
      await loadMaxBots()
    }
    showMaxModal.value = false
  } catch (e) {
    // Отказ MAX (неверный токен, вебхук не прописался) показываем словами: без
    // него окно просто «не закрывалось».
    maxFormError.value = e.response?.data?.detail || 'Ошибка сохранения'
  } finally {
    maxSaving.value = false
  }
}

async function toggleMaxActive(b) {
  maxToggling.value = b.id
  maxError.value = ''
  try {
    const res = await api.patch(`/max-bots/${b.id}`, { is_active: !b.is_active })
    replaceMaxBot(res.data)
  } catch (e) {
    maxError.value = e.response?.data?.detail || 'Не удалось переключить бота'
    // Галочка в таблице привязана к данным с бэка — перечитываем, чтобы она не
    // осталась в положении, до которого дело не дошло.
    await loadMaxBots()
  } finally {
    maxToggling.value = null
  }
}

async function checkMaxBot(b) {
  maxChecking.value = b.id
  maxError.value = ''
  try {
    const res = await api.post(`/max-bots/${b.id}/check`)
    replaceMaxBot(res.data)
  } catch (e) {
    maxError.value = e.response?.data?.detail || 'MAX не ответил'
  } finally {
    maxChecking.value = null
  }
}

async function doDeleteMaxBot() {
  maxSaving.value = true
  maxDeleteError.value = ''
  try {
    await api.delete(`/max-bots/${maxDeleteTarget.value.id}`)
    maxBots.value = maxBots.value.filter(b => b.id !== maxDeleteTarget.value.id)
    maxDeleteTarget.value = null
  } catch (e) {
    // Бота с перепиской бэк удалить не даст — объясняем, что делать вместо.
    maxDeleteError.value = e.response?.data?.detail || 'Не удалось удалить бота'
  } finally {
    maxSaving.value = false
  }
}

onMounted(async () => {
  // Метки после скриптов: экран показывает тексты приветствий, а они из scripts.
  await load()
  loadGroups()
  loadRefTags()
  loadMaxBots()
})

// Админка часто остаётся открытой во вкладке часами. Перечитываем ботов при
// переходе в их раздел: созданные с другого устройства или после рестарта
// сервиса не пропадут из старого локального состояния страницы.
watch(activeSection, (section) => {
  if (section === 'max-bots') loadMaxBots()
})
</script>
