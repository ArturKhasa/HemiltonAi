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
                <td colspan="7" class="px-4 py-10 text-center text-gray-400">Нет скриптов</td>
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
                  <div v-if="r.greeting_script_id" class="mt-1.5">
                    <textarea
                      v-model="greetingDrafts[r.greeting_script_id]"
                      rows="4"
                      class="w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
                    ></textarea>
                    <div class="flex items-center gap-2 mt-1">
                      <button
                        @click="saveGreetingText(r.greeting_script_id)"
                        :disabled="!greetingChanged(r.greeting_script_id)"
                        class="text-xs px-2.5 py-1 rounded-lg bg-brand-600 text-white disabled:opacity-40 hover:bg-brand-700"
                      >Сохранить текст</button>
                      <span v-if="greetingSaved === r.greeting_script_id" class="text-xs text-green-600">сохранено</span>
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
            <span class="text-xs text-gray-400">Адрес вебхука для Callback API: <span class="font-mono text-gray-500">https://&lt;домен&gt;/webhook/vk</span></span>
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
                <td class="px-4 py-3 text-gray-500 font-mono text-xs">{{ g.confirmation_code }}</td>
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
                    <button @click="groupDeleteTarget = g" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
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
            <label class="block text-xs text-gray-500 mb-1.5">Маркетинговый тег</label>
            <input
              v-model="form.marketing_tag"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              placeholder="Без # — пусто = для всех клиентов"
            />
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
            :disabled="saving || !form.condition.trim() || !form.phrase_text.trim()"
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
        <p class="text-sm text-gray-500 mb-6">ID группы: {{ groupDeleteTarget.group_id }}. Вебхуки от неё перестанут обрабатываться.</p>
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
import { ref, computed, onMounted } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const SECTIONS = [
  { id: 'scripts', label: 'Скрипты' },
  { id: 'ref-tags', label: 'Реф-метки' },
  { id: 'vk-groups', label: 'Группы ВК' },
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

const form = ref({ type_id: null, condition: '', phrase_text: '', marketing_tag: '', funnel_stage: '', follow_up_script_id: 0, is_active: true })

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
  form.value = { type_id: activeTypeId.value, condition: '', phrase_text: '', marketing_tag: '', funnel_stage: '', follow_up_script_id: 0, is_active: true }
  showModal.value = true
}

function openEdit(s) {
  editScript.value = s
  form.value = { type_id: s.type_id, condition: s.condition, phrase_text: s.phrase_text, marketing_tag: s.marketing_tag || '', funnel_stage: s.funnel_stage || '', follow_up_script_id: s.follow_up_script_id || 0, is_active: s.is_active }
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
    if (editScript.value) {
      const res = await api.patch(`/scripts/${editScript.value.id}`, { ...form.value, marketing_tag, funnel_stage, follow_up_script_id })
      const idx = scripts.value.findIndex(s => s.id === editScript.value.id)
      if (idx !== -1) scripts.value[idx] = res.data
    } else {
      const res = await api.post('/scripts/', {
        condition: form.value.condition,
        phrase_text: form.value.phrase_text,
        type_id: form.value.type_id,
        marketing_tag,
        funnel_stage,
        follow_up_script_id,
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
const refForm = ref({ tag: '', type_id: null, is_active: true, note: '' })

// Черновики текстов приветствий: правим у себя, сохраняем по кнопке.
const greetingDrafts = ref({})
const greetingSaved = ref(null)

const greetingScripts = computed(() =>
  scripts.value.filter(s => (s.condition || '').toLowerCase().includes('первое приветственное'))
)

function syncGreetingDrafts() {
  for (const r of refTags.value) {
    if (!r.greeting_script_id) continue
    const src = scripts.value.find(s => s.id === r.greeting_script_id)
    if (src) greetingDrafts.value[r.greeting_script_id] = src.phrase_text
  }
}

const greetingChanged = (id) => {
  const src = scripts.value.find(s => s.id === id)
  return !!src && greetingDrafts.value[id] !== undefined && greetingDrafts.value[id] !== src.phrase_text
}


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
  refForm.value = { tag: '', type_id: activeTypeId.value, is_active: true, note: '' }
  showRefModal.value = true
}

function openRefEdit(r) {
  editRefTag.value = r
  refError.value = ''
  refForm.value = { tag: r.tag, type_id: r.type_id, is_active: r.is_active, note: r.note || '' }
  showRefModal.value = true
}

async function saveRefTag() {
  refSaving.value = true
  refError.value = ''
  try {
    if (editRefTag.value) {
      const res = await api.patch(`/ref-tags/${editRefTag.value.id}`, {
        tag: refForm.value.tag, is_active: refForm.value.is_active, note: refForm.value.note,
      })
      const i = refTags.value.findIndex(x => x.id === editRefTag.value.id)
      if (i !== -1) refTags.value[i] = res.data
    } else {
      const res = await api.post('/ref-tags/', refForm.value)
      refTags.value.push(res.data)
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

async function bindGreeting(r, scriptId) {
  // 0 вместо null: PATCH на бэке режет null-поля (exclude_none).
  const res = await api.patch(`/ref-tags/${r.id}`, { greeting_script_id: scriptId })
  r.greeting_script_id = res.data.greeting_script_id
  syncGreetingDrafts()
}

async function saveGreetingText(scriptId) {
  const res = await api.patch(`/scripts/${scriptId}`, { phrase_text: greetingDrafts.value[scriptId] })
  const i = scripts.value.findIndex(s => s.id === scriptId)
  if (i !== -1) scripts.value[i] = res.data
  greetingSaved.value = scriptId
  setTimeout(() => { if (greetingSaved.value === scriptId) greetingSaved.value = null }, 2000)
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
const groupError = ref('')

const groupForm = ref({ group_id: null, name: '', access_token: '', confirmation_code: '', secret_key: '', dialog_type_id: null, is_active: true })

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
  try {
    await api.delete(`/vk-groups/${groupDeleteTarget.value.id}`)
    vkGroups.value = vkGroups.value.filter(g => g.id !== groupDeleteTarget.value.id)
    groupDeleteTarget.value = null
  } finally {
    groupSaving.value = false
  }
}

onMounted(async () => {
  // Метки после скриптов: экран показывает тексты приветствий, а они из scripts.
  await load()
  loadGroups()
  loadRefTags()
})
</script>
