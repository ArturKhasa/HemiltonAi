<template>
  <div class="flex h-screen bg-gray-100">
    <!-- Sidebar -->
    <aside class="w-72 bg-white border-r flex flex-col">
      <div class="p-4 border-b flex items-center justify-between">
        <span class="font-semibold text-gray-800">Hemilton AI</span>
        <div class="relative">
          <button @click="showMenu = !showMenu" class="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
              <circle cx="10" cy="4" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="10" cy="16" r="1.5"/>
            </svg>
          </button>
          <div v-if="showMenu" class="fixed inset-0 z-10" @click="showMenu = false"></div>
          <div v-if="showMenu" class="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-20 min-w-36">
            <button
              v-if="isAdmin"
              @click="showMenu = false; $router.push('/admin')"
              class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >Скрипты</button>
            <button
              v-if="isAdmin"
              @click="showMenu = false; $router.push('/admin/ping-rules')"
              class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >Пинг-правила</button>
            <button
              v-if="isAdmin"
              @click="showMenu = false; $router.push('/admin/users')"
              class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >Пользователи</button>
            <button
              @click="showMenu = false; auth.logout(); $router.push('/login')"
              class="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-gray-50"
            >Выйти</button>
          </div>
        </div>
      </div>

      <div class="p-3 border-b flex gap-2">
        <button v-if="filterShowTest" @click="showNewChat = true" class="flex-1 bg-brand-600 text-white py-2 rounded-lg text-sm hover:bg-brand-700 font-medium">
          + Новый чат
        </button>
        <button
          @click="showFilters = true"
          :class="[
            'px-3 py-2 rounded-lg text-sm border transition-colors',
            hasActiveFilters
              ? 'border-brand-400 text-brand-600 bg-brand-50'
              : 'border-gray-200 text-gray-500 hover:bg-gray-50'
          ]"
          title="Фильтры"
        >
          <span>⚙</span>
          <span v-if="hasActiveFilters" class="ml-1 text-xs font-medium">●</span>
        </button>
        <button
          v-if="filterShowReal"
          @click="openPingReview"
          class="px-3 py-2 rounded-lg text-sm border border-brand-400 text-brand-600 bg-brand-50 hover:bg-brand-100 font-medium transition-colors"
          title="Просмотр реальных диалогов"
        >Пинг</button>
        <button v-if="filterShowTest && !filterShowReal" @click="showDeleteAll = true" :disabled="dialogs.length === 0" class="px-3 py-2 rounded-lg text-sm border border-red-200 text-red-500 hover:bg-red-50 disabled:opacity-30 disabled:cursor-not-allowed" title="Удалить все чаты">
          🗑
        </button>
      </div>

      <div v-if="dialogs.length > 0" class="px-4 py-2 border-b text-xs text-gray-400">
        Найдено: {{ dialogsCount }}
      </div>

      <div ref="dialogListEl" class="flex-1 overflow-y-auto" @scroll="onDialogListScroll">
        <div v-if="dialogsError" class="p-4 text-sm text-center mt-4">
          <p class="text-red-600 mb-2">{{ dialogsError }}</p>
          <button @click="loadDialogs()" class="px-3 py-1.5 border rounded-lg text-xs hover:bg-gray-50 text-gray-600">Повторить</button>
        </div>
        <div v-else-if="dialogs.length === 0" class="p-4 text-sm text-gray-400 text-center mt-4">Нет чатов</div>
        <div
          v-for="d in dialogs" :key="d.id"
          @click="openDialog(d.id)"
          :class="[
            'group relative w-full text-left px-4 py-3 border-b hover:bg-gray-50 transition-colors cursor-pointer',
            activeDialogId === d.id ? 'bg-brand-50 border-l-2 border-l-brand-500' : ''
          ]"
        >
          <p class="text-sm font-medium text-gray-800 truncate pr-6">{{ leadTitle(d) }}</p>
          <p v-if="fullName(d)" class="text-xs text-gray-400 truncate">ID {{ d.vk_user_id }}</p>
          <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
            <p class="text-xs text-gray-400">{{ formatDate(d.last_message_at || d.created_at) }}</p>
            <span :class="[
              'text-[10px] font-medium px-1.5 py-0.5 rounded-full',
              d.ai_provider === 'anthropic'
                ? 'bg-orange-100 text-orange-600'
                : d.ai_provider === 'minimax'
                  ? 'bg-purple-100 text-purple-700'
                  : d.ai_provider === 'qwen'
                    ? 'bg-brand-100 text-brand-700'
                    : 'bg-green-100 text-green-700'
            ]">{{ d.ai_provider === 'anthropic' ? 'Claude' : d.ai_provider === 'minimax' ? 'MiniMax' : d.ai_provider === 'qwen' ? 'Qwen' : 'ChatGPT' }}</span>
            <span v-if="d.current_status" :class="['text-[10px] font-medium px-1.5 py-0.5 rounded-full', statusColor(d.current_status)]">
              {{ d.current_status }}
            </span>
            <!-- Только когда пауза НЕ следует из статуса: «Нужен куратор» уже
                 означает, что диалог передан человеку, и второй бейдж рядом с ним
                 читался как дубль. Оператор, перехвативший диалог из ВК, статус не
                 меняет — вот там метка и нужна. -->
            <span
              v-if="d.ai_paused && d.current_status !== 'Нужен куратор'"
              class="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-700"
              title="ИИ на паузе — отвечает живой оператор"
            >⏸ ручной</span>
          </div>
          <button
            v-if="d.is_test"
            @click.stop="showDeleteOne = d.id"
            class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-opacity"
            title="Удалить чат"
          >🗑</button>
        </div>
        <div v-if="dialogsLoading && dialogs.length > 0" class="p-3 text-xs text-gray-400 text-center">Загрузка...</div>
      </div>
    </aside>

    <!-- Main chat area -->
    <div class="flex-1 flex flex-col">
      <template v-if="activeDialogId">
        <!-- Header -->
        <div class="bg-white border-b px-6 py-3 flex items-center gap-3">
          <div>
            <p class="font-medium text-gray-800">
              <a
                v-if="activeDialog?.vk_user_id"
                :href="`https://vk.com/id${activeDialog.vk_user_id}`"
                target="_blank" rel="noopener"
                class="hover:underline"
              >{{ leadTitle(activeDialog) }}</a>
              <template v-else>{{ leadTitle(activeDialog) }}</template>
            </p>
            <p v-if="fullName(activeDialog)" class="text-xs text-gray-400">VK ID: {{ activeDialog?.vk_user_id ?? '—' }}</p>
          </div>
          <div class="flex items-center gap-2 ml-4">
            <span class="text-xs text-gray-500">Статус:</span>
            <select
              :value="activeDialog?.current_status || ''"
              @change="changeStatus($event.target.value)"
              :disabled="statusChanging"
              class="text-xs border rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
            >
              <option value="" disabled>— не задан —</option>
              <option v-for="s in activeStatuses" :key="s.id" :value="s.name">{{ s.name }}</option>
            </select>
            <span v-if="statusChanging" class="text-xs text-gray-400">...</span>
          </div>
          <div v-if="activeDialog?.funnel_stage" class="flex items-center gap-1 ml-2">
            <span class="text-xs text-gray-500">Стадия:</span>
            <span
              class="text-xs px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 border border-violet-200"
              :title="activeDialog.funnel_stage"
            >{{ funnelStageLabel(activeDialog.funnel_stage) }}</span>
          </div>
          <!-- Пауза ИИ: ставится автоматически, когда живой оператор отвечает из ВК -->
          <div class="flex items-center gap-2 ml-2">
            <template v-if="aiPaused">
              <span class="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 border border-orange-200 font-medium">ИИ на паузе (оператор)</span>
              <button
                v-if="canSeeRealDialogs"
                @click="toggleAiPause(false)"
                :disabled="aiPauseLoading"
                class="text-xs px-2 py-1 rounded-lg border border-green-300 text-green-700 hover:bg-green-50 disabled:opacity-50 font-medium"
              >Возобновить ИИ</button>
            </template>
            <button
              v-else-if="canSeeRealDialogs"
              @click="toggleAiPause(true)"
              :disabled="aiPauseLoading"
              class="text-xs px-2 py-1 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >Пауза ИИ</button>
            <span v-if="vkBlocked" class="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 border border-red-200 font-medium">ВК заблокировал отправку</span>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <div v-if="activeDialog?.marketing_tags?.length" class="flex flex-wrap items-center gap-1">
              <span
                v-for="tag in activeDialog.marketing_tags"
                :key="tag"
                class="text-xs px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-200"
              >{{ tag }}</span>
            </div>
            <span class="text-xs text-gray-400">Dialog #{{ activeDialogId }}</span>
            <div class="relative">
              <button
                @click="showExportMenu = !showExportMenu"
                class="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                title="Действия"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <circle cx="10" cy="4" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="10" cy="16" r="1.5"/>
                </svg>
              </button>
              <div v-if="showExportMenu" class="fixed inset-0 z-10" @click="showExportMenu = false"></div>
              <div v-if="showExportMenu" class="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-20 min-w-44">
                <button
                  @click="showExportMenu = false; exportDialogHtml()"
                  class="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >Выгрузить в HTML</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Ping state -->
        <div v-if="pingState" class="bg-amber-50 border-b border-amber-200 px-6 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span class="font-medium text-amber-700">🔔 Пинг</span>
          <span class="text-gray-600">Воронка: <span class="font-medium text-gray-800">{{ pingState.funnel_type }}</span></span>
          <span
            v-if="pingState.funnel_reason"
            class="text-gray-500 italic basis-full whitespace-normal break-words"
          >— {{ pingState.funnel_reason }}</span>
          <span class="text-gray-600">Шаг: <span class="font-medium text-gray-800">{{ pingState.current_step }}</span></span>
          <span :class="pingState.is_completed ? 'text-green-700' : 'text-amber-700'">
            {{ pingState.is_completed ? '✓ Завершена' : '● Активна' }}
          </span>
          <span v-if="pingState.marketing_tag" class="text-gray-600">Тег: <span class="font-medium text-gray-800">{{ pingState.marketing_tag }}</span></span>
          <span class="text-gray-600">Следующий: <span class="font-medium text-gray-800">{{ formatFullDateTime(pingState.next_ping_due_at) }}</span></span>
          <button
            @click="showResetPing = true"
            title="Выключить воронку (переопределится заново)"
            class="ml-auto w-5 h-5 flex items-center justify-center rounded-full text-amber-600 hover:bg-amber-200 hover:text-amber-800 transition-colors"
          >✕</button>
        </div>

        <!-- Messages -->
        <div ref="messagesEl" class="flex-1 overflow-y-auto p-6 space-y-4">
          <template v-for="msg in messages" :key="msg.id">
            <div :class="['flex flex-col', msg.role === 'client' ? 'items-end' : 'items-start']">
              <!-- Source label -->
              <div class="mb-0.5 px-1">
                <span v-if="msg.role === 'curator'" class="text-xs text-purple-500 font-medium">👤 Оператор (ВК)</span>
                <span v-else-if="msg.role === 'ai' && msg.is_ping" class="text-xs text-amber-500 font-medium">🔔 Пинг</span>
                <span v-else-if="msg.role === 'ai'" class="text-xs text-emerald-500 font-medium">🤖 AI</span>
              </div>
              <div :class="[
                'max-w-xl px-4 py-2.5 rounded-2xl text-sm shadow-sm',
                msg.role === 'client'
                  ? 'bg-brand-600 text-white rounded-br-sm'
                  : msg.role === 'curator'
                    ? 'bg-purple-50 border border-purple-200 rounded-bl-sm text-gray-800'
                    : msg.is_ping
                      ? 'bg-amber-50 border border-amber-200 rounded-bl-sm text-gray-800'
                      : 'bg-white border rounded-bl-sm text-gray-800',
                msg.need_curator ? 'border-orange-400 border-2' : '',
              ]">
                <template v-for="(part, pi) in parseMessageParts(msg.text)" :key="pi">
                  <p v-if="part.type === 'text'" class="leading-relaxed whitespace-pre-wrap">{{ part.value }}</p>
                  <img
                    v-else-if="part.type === 'image'"
                    :src="part.value"
                    @click="preview = { type: 'image', src: part.value }"
                    class="mt-1 rounded-lg max-w-full max-h-64 object-contain cursor-zoom-in hover:opacity-90 transition-opacity"
                    loading="lazy"
                    title="Открыть во весь экран"
                  />
                  <a
                    v-else-if="part.type === 'link'"
                    :href="part.value"
                    target="_blank"
                    rel="noopener"
                    class="block mt-1 text-brand-600 underline break-all"
                  >{{ part.value }}</a>
                  <button
                    v-else-if="part.type === 'video'"
                    @click="preview = { type: 'video', ...part }"
                    class="inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-xs hover:bg-gray-200 transition-colors cursor-pointer"
                    title="Посмотреть видео"
                  >🎬 видео</button>
                  <span v-else class="inline-block mt-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs">{{ part.value }}</span>
                </template>
                <p v-if="msg.role === 'ai' && msg.selected_script" class="mt-1 text-xs text-gray-400">{{ msg.selected_script }}</p>
                <p v-if="msg.role === 'ai' && msg.source_script_id" class="mt-1 text-xs text-gray-400">script #{{ msg.source_script_id }}</p>
                <div v-if="msg.files && msg.files.length" class="mt-2 flex flex-col gap-2">
                  <template v-for="(url, i) in msg.files" :key="i">
                    <audio
                      v-if="isAudioUrl(url)"
                      :src="url"
                      controls
                      class="w-72 rounded-lg"
                    />
                    <img
                      v-else
                      :src="url"
                      @click="preview = { type: 'image', src: url }"
                      class="rounded-lg max-w-full max-h-64 object-contain cursor-zoom-in hover:opacity-90 transition-opacity"
                      loading="lazy"
                      title="Открыть во весь экран"
                    />
                  </template>
                </div>
                <div v-if="msg.audio_urls && msg.audio_urls.length" class="mt-2 flex flex-col gap-2">
                  <audio
                    v-for="(url, i) in msg.audio_urls"
                    :key="i"
                    :src="url"
                    controls
                    class="w-full max-w-xs rounded-lg"
                  />
                </div>
                <div class="mt-1 flex items-center justify-between gap-2">
                  <div v-if="msg.role !== 'client'" class="flex gap-2 text-xs text-gray-400">
                    <span v-if="msg.confidence_score !== null && msg.confidence_score !== undefined">
                      {{ (msg.confidence_score * 100).toFixed(0) }}% уверенность
                    </span>
                    <span
                      v-if="msg.need_curator"
                      class="text-orange-500 font-medium"
                      :title="msg.curator_trigger
                        ? 'Ответ клиенту ушёл, дальше диалог ведёт менеджер — ИИ на паузе'
                        : 'Ответ не отправлен клиенту, ждёт проверки куратора'"
                    >⚠ На проверку куратору{{ msg.curator_trigger ? ': ' + msg.curator_trigger : '' }}</span>
                  </div>
                  <div v-else></div>
                  <span v-if="msg.created_at" :class="['text-xs ml-auto', msg.role === 'client' ? 'text-brand-200' : 'text-gray-400']">
                    {{ formatMsgTime(msg.created_at) }}
                  </span>
                </div>
              </div>
              <!-- Feedback button for AI messages -->
              <div v-if="msg.role === 'ai'" class="mt-1 px-1 flex gap-2">
                <button
                  @click="openFeedback(msg)"
                  :class="[
                    'text-xs px-2 py-0.5 rounded-lg border transition-colors',
                    msg.feedback_id
                      ? 'border-amber-300 text-amber-600 bg-amber-50 hover:bg-amber-100'
                      : 'border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                  ]"
                >
                  {{ msg.feedback_id ? 'Отредактировать ошибку' : 'Указать ошибку' }}
                </button>
                <button
                  v-if="msg.has_context"
                  @click="openContext(msg)"
                  class="text-xs px-2 py-0.5 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Размышления ИИ
                </button>
              </div>
            </div>
          </template>
          <div v-if="sending" class="flex justify-start">
            <div class="bg-white border rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-gray-400 shadow-sm">
              Генерирую ответ...
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="bg-white border-t p-4">
          <!-- Боевой диалог: ответ живого менеджера. Раньше сюда писать было
               нельзя вовсе («только просмотр»), и диалог с меткой «Нужен куратор»
               оставалось разве что смотреть. Отправка забирает диалог у ИИ. -->
          <template v-if="activeDialog?.is_test === false">
            <div class="flex items-center gap-2 mb-2 text-xs text-gray-500 flex-wrap">
              <span>✍️ Ответ от лица менеджера уйдёт клиенту в ВК.</span>
              <span v-if="!aiPaused" class="text-amber-600">ИИ встанет на паузу, пинги остановятся.</span>
              <span v-else class="text-gray-400">ИИ уже на паузе.</span>
              <button
                type="button"
                :disabled="confirmingPayment"
                @click="togglePaymentConfirmed"
                class="ml-auto px-2 py-1 rounded-lg border text-xs"
                :class="paymentConfirmed
                  ? 'border-green-300 text-green-700 bg-green-50'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-50'"
                :title="paymentConfirmed
                  ? 'Оплата подтверждена: ИИ может вести шаги после оплаты'
                  : 'Отметить, что предоплата получена'"
              >
                {{ paymentConfirmed ? '💰 Оплата подтверждена' : 'Подтвердить оплату' }}
              </button>
            </div>
            <div v-if="managerFiles.length" class="flex flex-wrap gap-2 mb-2">
              <div v-for="(f, i) in managerFiles" :key="i" class="relative">
                <img v-if="f.preview" :src="f.preview" class="h-16 w-16 object-cover rounded-lg border" />
                <div v-else class="h-16 w-24 rounded-lg border bg-gray-50 flex items-center justify-center px-1">
                  <span class="text-[10px] text-gray-500 text-center break-all leading-tight">{{ f.name }}</span>
                </div>
                <button @click="removeManagerFile(i)" class="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-xs leading-none">×</button>
                <div v-if="f.uploading" class="absolute inset-0 bg-black/30 rounded-lg flex items-center justify-center">
                  <span class="text-white text-xs">…</span>
                </div>
              </div>
            </div>
            <input ref="managerFileInput" type="file" accept="image/*,video/*" multiple class="hidden" @change="onManagerFilesSelected" />
            <form @submit.prevent="sendAsManager" class="flex gap-3">
              <button
                type="button"
                :disabled="sendingManager"
                @click="managerFileInput.click()"
                class="px-3 py-2.5 border rounded-xl text-gray-500 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                title="Прикрепить фото или видео"
              >📎</button>
              <textarea
                v-model="managerInput"
                :disabled="sendingManager"
                @keydown.enter.exact.prevent="sendAsManager"
                placeholder="Ответить клиенту... (Enter — отправить)"
                rows="1"
                class="flex-1 border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none disabled:opacity-50"
              />
              <button
                type="submit"
                :disabled="sendingManager || (!managerInput.trim() && !managerFiles.length) || managerFiles.some(f => f.uploading)"
                class="bg-brand-600 text-white px-5 py-2.5 rounded-xl hover:bg-brand-700 disabled:opacity-50 text-sm font-medium"
              >
                {{ sendingManager ? 'Отправка...' : 'Ответить' }}
              </button>
            </form>
            <p v-if="managerError" class="text-xs text-red-600 mt-2">{{ managerError }}</p>
          </template>
          <template v-else>
          <div v-if="pendingFiles.length" class="flex flex-wrap gap-2 mb-2">
            <div v-for="(f, i) in pendingFiles" :key="i" class="relative">
              <img :src="f.preview" class="h-16 w-16 object-cover rounded-lg border" />
              <button @click="removeFile(i)" class="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-xs leading-none">×</button>
              <div v-if="f.uploading" class="absolute inset-0 bg-black/30 rounded-lg flex items-center justify-center">
                <span class="text-white text-xs">...</span>
              </div>
            </div>
          </div>
          <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="onFilesSelected" />
          <form @submit.prevent="sendMessage" class="flex gap-3">
            <button
              type="button"
              :disabled="sending"
              @click="fileInput.click()"
              class="px-3 py-2.5 border rounded-xl text-gray-500 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              title="Прикрепить фото"
            >📎</button>
            <textarea
              v-model="input"
              :disabled="sending"
              @keydown.enter.exact.prevent="sendMessage"
              placeholder="Введите сообщение... (Enter — отправить)"
              rows="1"
              class="flex-1 border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none disabled:opacity-50"
            />
            <button type="submit" :disabled="sending || (!input.trim() && !pendingFiles.length) || pendingFiles.some(f => f.uploading)" class="bg-brand-600 text-white px-5 py-2.5 rounded-xl hover:bg-brand-700 disabled:opacity-50 text-sm font-medium">
              Отправить
            </button>
          </form>
          </template>
        </div>
      </template>

      <!-- Empty state -->
      <div v-else class="flex-1 flex items-center justify-center">
        <div class="text-center text-gray-400">
          <p class="text-lg mb-2">Выберите чат или создайте новый</p>
          <button v-if="filterShowTest" @click="showNewChat = true" class="bg-brand-600 text-white px-6 py-2.5 rounded-xl text-sm hover:bg-brand-700">
            + Новый чат
          </button>
        </div>
      </div>
    </div>

    <!-- Attachment preview modal (video / photo) -->
    <div
      v-if="preview"
      class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      @click.self="preview = null"
    >
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-3xl overflow-hidden">
        <div class="px-4 py-3 flex items-center justify-between border-b">
          <span class="text-sm font-medium text-gray-700">
            {{ preview.type === 'video' ? '🎬 Видео из сообщения' : '📷 Фото из сообщения' }}
          </span>
          <button @click="preview = null" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>

        <div v-if="preview.type === 'video'" class="bg-black aspect-video">
          <iframe
            :src="preview.embed"
            class="w-full h-full"
            frameborder="0"
            allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
            allowfullscreen
          ></iframe>
        </div>
        <div v-else class="bg-black flex items-center justify-center">
          <img :src="preview.src" class="max-h-[75vh] max-w-full object-contain" />
        </div>

        <div class="px-4 py-3 border-t">
          <a
            :href="preview.type === 'video' ? preview.href : preview.src"
            target="_blank"
            rel="noopener"
            class="text-xs text-brand-600 underline break-all"
          >Открыть оригинал</a>
          <p v-if="preview.type === 'video'" class="text-xs text-gray-400 mt-1">
            Если плеер пустой — ролик закрыт для встраивания, откройте по ссылке.
          </p>
        </div>
      </div>
    </div>

    <!-- Delete all chats confirmation modal -->
    <div v-if="showDeleteAll" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="showDeleteAll = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
        <h2 class="text-lg font-semibold mb-2">Удалить все чаты?</h2>
        <p class="text-sm text-gray-500 mb-5">Это действие удалит все {{ dialogs.length }} чат(ов) и историю сообщений. Отменить нельзя.</p>
        <div class="flex gap-2">
          <button @click="deleteAllChats" :disabled="deleteAllLoading" class="flex-1 bg-red-600 text-white py-2 rounded-lg text-sm hover:bg-red-700 disabled:opacity-50">
            {{ deleteAllLoading ? 'Удаляем...' : 'Удалить всё' }}
          </button>
          <button @click="showDeleteAll = false" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Отмена</button>
        </div>
      </div>
    </div>

    <!-- Delete single chat confirmation modal -->
    <div v-if="showDeleteOne" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="showDeleteOne = null">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
        <h2 class="text-lg font-semibold mb-2">Удалить чат?</h2>
        <p class="text-sm text-gray-500 mb-5">История сообщений будет удалена. Отменить нельзя.</p>
        <div class="flex gap-2">
          <button @click="deleteDialog(showDeleteOne)" :disabled="deleteOneLoading" class="flex-1 bg-red-600 text-white py-2 rounded-lg text-sm hover:bg-red-700 disabled:opacity-50">
            {{ deleteOneLoading ? 'Удаляем...' : 'Удалить' }}
          </button>
          <button @click="showDeleteOne = null" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Отмена</button>
        </div>
      </div>
    </div>

    <!-- Reset ping funnel confirmation modal -->
    <div v-if="showResetPing" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="showResetPing = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
        <h2 class="text-lg font-semibold mb-2">Выключить воронку?</h2>
        <p class="text-sm text-gray-500 mb-5">Текущее состояние пинга будет удалено. Воронка определится заново при следующей проверке.</p>
        <div class="flex gap-2">
          <button @click="resetPingState" :disabled="resetPingLoading" class="flex-1 bg-red-600 text-white py-2 rounded-lg text-sm hover:bg-red-700 disabled:opacity-50">
            {{ resetPingLoading ? 'Выключаем...' : 'Выключить' }}
          </button>
          <button @click="showResetPing = false" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Отмена</button>
        </div>
      </div>
    </div>

    <!-- Filters modal -->
    <div v-if="showFilters" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" @click.self="showFilters = false; showDateDropdown = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-screen overflow-y-auto">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold">Фильтры диалогов</h2>
          <button
            @click="resetFilters"
            class="px-3 py-1.5 border rounded-lg text-xs hover:bg-gray-50 text-gray-600"
          >Сбросить</button>
        </div>
        <div class="space-y-4">
          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">Тип диалогов</p>
            <select
              :value="dialogTypeFilterValue"
              @change="setDialogTypeFilter($event.target.value)"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option value="test">Тестовые диалоги</option>
              <option v-if="canSeeRealDialogs" value="real">Реальные диалоги</option>
              <option v-if="canSeeRealDialogs" value="all">Все диалоги</option>
            </select>
          </div>
          <div class="flex gap-4">
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-gray-700 mb-2">Дата</p>
              <div class="relative">
                <button
                  type="button"
                  @click="showDateDropdown = !showDateDropdown"
                  class="w-full flex items-center justify-between px-3 py-2 border rounded-lg text-sm bg-white hover:bg-gray-50 focus:outline-none"
                >
                  <span class="flex items-center gap-2 text-gray-700">
                    <span>📅</span>
                    <span>{{ selectedDateLabel }}</span>
                  </span>
                  <span class="text-gray-400 text-xs">{{ showDateDropdown ? '▲' : '▼' }}</span>
                </button>
                <div v-if="showDateDropdown" class="absolute z-10 mt-1 w-full bg-white border rounded-xl shadow-lg py-1 max-h-64 overflow-y-auto">
                  <button
                    v-for="preset in DATE_PRESETS"
                    :key="preset.value"
                    type="button"
                    @click="filterDatePreset = preset.value; showDateDropdown = false"
                    :class="[
                      'w-full text-left px-4 py-2 text-sm hover:bg-gray-50 transition-colors',
                      filterDatePreset === preset.value ? 'text-brand-600 font-medium' : 'text-gray-700'
                    ]"
                  >{{ preset.label }}</button>
                </div>
              </div>
              <div v-if="filterDatePreset === 'custom'" class="flex gap-2 mt-2">
                <div class="flex-1">
                  <label class="text-xs text-gray-500 mb-1 block">От</label>
                  <input type="date" v-model="filterDateFrom" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500" />
                </div>
                <div class="flex-1">
                  <label class="text-xs text-gray-500 mb-1 block">До</label>
                  <input type="date" v-model="filterDateTo" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500" />
                </div>
              </div>
            </div>

            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-gray-700 mb-2">Первый контакт</p>
              <div class="relative">
                <button
                  type="button"
                  @click="showClientDateDropdown = !showClientDateDropdown"
                  class="w-full flex items-center justify-between px-3 py-2 border rounded-lg text-sm bg-white hover:bg-gray-50 focus:outline-none"
                >
                  <span class="flex items-center gap-2 text-gray-700">
                    <span>📅</span>
                    <span>{{ selectedClientDateLabel }}</span>
                  </span>
                  <span class="text-gray-400 text-xs">{{ showClientDateDropdown ? '▲' : '▼' }}</span>
                </button>
                <div v-if="showClientDateDropdown" class="absolute z-10 mt-1 w-full bg-white border rounded-xl shadow-lg py-1 max-h-64 overflow-y-auto">
                  <button
                    v-for="preset in DATE_PRESETS"
                    :key="preset.value"
                    type="button"
                    @click="filterClientDatePreset = preset.value; showClientDateDropdown = false"
                    :class="[
                      'w-full text-left px-4 py-2 text-sm hover:bg-gray-50 transition-colors',
                      filterClientDatePreset === preset.value ? 'text-brand-600 font-medium' : 'text-gray-700'
                    ]"
                  >{{ preset.label }}</button>
                </div>
              </div>
              <div v-if="filterClientDatePreset === 'custom'" class="flex gap-2 mt-2">
                <div class="flex-1">
                  <label class="text-xs text-gray-500 mb-1 block">От</label>
                  <input type="date" v-model="filterClientDateFrom" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500" />
                </div>
                <div class="flex-1">
                  <label class="text-xs text-gray-500 mb-1 block">До</label>
                  <input type="date" v-model="filterClientDateTo" class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500" />
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeStatuses.length">
            <div class="flex items-center justify-between mb-2">
              <p class="text-sm font-medium text-gray-700">Статусы</p>
              <label class="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  :checked="allStatusesSelected"
                  @change="toggleAllStatuses"
                  class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                />
                <span class="text-xs text-gray-500">Выбрать все</span>
              </label>
            </div>
            <div class="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1">
              <label
                v-for="s in activeStatuses"
                :key="s.id"
                class="flex items-center gap-2 cursor-pointer select-none"
              >
                <input
                  type="checkbox"
                  :value="s.name"
                  v-model="filterStatuses"
                  class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                />
                <span :class="['text-xs font-medium px-1.5 py-0.5 rounded-full', statusColor(s.name)]">{{ s.name }}</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  value="__none__"
                  v-model="filterStatuses"
                  class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                />
                <span class="text-xs font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500">Без статуса</span>
              </label>
            </div>
          </div>

          <div v-if="dialogTypes.length > 0">
            <p class="text-sm font-medium text-gray-700 mb-2">Направление</p>
            <select
              v-model="filterDialogTypeId"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option :value="null">Все типы</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>

          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">Воронка пинга</p>
            <select
              v-model="filterPingFunnelType"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option :value="null">Все</option>
              <option value="__none__">Не указано</option>
              <option v-for="ft in pingFunnelTypes" :key="ft" :value="ft">{{ ft }}</option>
            </select>
          </div>

          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">Стадия диалога</p>
            <select
              v-model="filterFunnelStage"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option :value="null">Все</option>
              <option value="__none__">Не указано</option>
              <option v-for="(label, stage) in FUNNEL_STAGE_LABELS" :key="stage" :value="stage">{{ label }}</option>
            </select>
          </div>

          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">AI провайдер</p>
            <div class="flex flex-col gap-2">
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" value="openai" v-model="filterAiProviders" class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">OpenAI</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" value="anthropic" v-model="filterAiProviders" class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">Claude</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" value="minimax" v-model="filterAiProviders" class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">MiniMax</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" value="qwen" v-model="filterAiProviders" class="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">Qwen</span>
              </label>
            </div>
          </div>

          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">Последнее сообщение от</p>
            <div class="flex flex-col gap-2">
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="radio" value="" v-model="filterLastMessageFrom" class="w-4 h-4 border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">Все</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="radio" value="client" v-model="filterLastMessageFrom" class="w-4 h-4 border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">От клиента</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="radio" value="ai_reply" v-model="filterLastMessageFrom" class="w-4 h-4 border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">Ответ от ИИ</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="radio" value="ai_ping" v-model="filterLastMessageFrom" class="w-4 h-4 border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">Пинг от ИИ</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input type="radio" value="curator" v-model="filterLastMessageFrom" class="w-4 h-4 border-gray-300 text-brand-600 focus:ring-brand-500" />
                <span class="text-sm text-gray-700">От куратора</span>
              </label>
            </div>
          </div>

          <div>
            <p class="text-sm font-medium text-gray-700 mb-2">VK ID клиента</p>
            <input
              type="text"
              v-model="filterClientId"
              placeholder="VK ID (несколько через ;)"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        </div>
        <div class="flex gap-2 mt-5">
          <button
            @click="applyFilters"
            class="flex-1 bg-brand-600 text-white py-2 rounded-lg text-sm hover:bg-brand-700 font-medium"
          >Применить</button>
        </div>
        <button
          @click="exportDialogsCsv"
          :disabled="csvExporting"
          class="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span v-if="csvExporting">Выгрузка...</span>
          <span v-else>Выгрузить CSV</span>
        </button>
        <button
          @click="exportClientIds"
          :disabled="idsExporting"
          class="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span v-if="idsExporting">Копирование...</span>
          <span v-else-if="idsCopied">Скопировано ✓</span>
          <span v-else>Скопировать ID клиентов</span>
        </button>
      </div>
    </div>

    <!-- Feedback modal -->
    <div v-if="feedbackModal.show" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="feedbackModal.show = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
        <h2 class="text-lg font-semibold mb-1">Правило для ИИ</h2>
        <p class="text-xs text-gray-400 mb-3">Опишите ошибку или что нужно исправить. Это правило будет применяться ко всем следующим ответам.</p>
        <div class="flex flex-wrap gap-1.5 mb-3">
          <button
            v-for="preset in feedbackPresets"
            :key="preset.label"
            @click="feedbackModal.text = preset.rule"
            type="button"
            class="px-2.5 py-1 border rounded-full text-xs text-gray-600 hover:bg-gray-50 hover:border-brand-400"
          >{{ preset.label }}</button>
        </div>
        <textarea
          v-model="feedbackModal.text"
          rows="4"
          autofocus
          placeholder="Например: Не называть цену без выявления потребности клиента"
          class="w-full border rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
        />
        <p v-if="feedbackModal.error" class="text-red-500 text-xs mt-1">{{ feedbackModal.error }}</p>
        <div class="flex gap-2 mt-4">
          <button
            @click="saveFeedback"
            :disabled="feedbackModal.loading || feedbackModal.text.trim().length < 30"
            class="flex-1 bg-brand-600 text-white py-2 rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50"
          >{{ feedbackModal.loading ? 'Сохраняем...' : 'Сохранить' }}</button>
        <p v-if="feedbackModal.text.trim().length > 0 && feedbackModal.text.trim().length < 30" class="text-xs text-gray-400 mt-1">Минимум 30 символов ({{ feedbackModal.text.trim().length }}/30)</p>
          <button
            v-if="feedbackModal.feedbackId"
            @click="deleteFeedback"
            :disabled="feedbackModal.loading"
            class="px-4 py-2 border border-red-200 text-red-500 rounded-lg text-sm hover:bg-red-50 disabled:opacity-50"
          >Удалить</button>
          <button @click="feedbackModal.show = false" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Отмена</button>
        </div>
      </div>
    </div>

    <!-- AI context modal -->
    <div v-if="contextModal.show" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" @click.self="contextModal.show = false">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div class="flex items-center justify-between p-5 border-b">
          <div>
            <h2 class="text-lg font-semibold">Размышления ИИ</h2>
            <p v-if="contextModal.model" class="text-xs text-gray-400 mt-0.5">{{ contextModal.provider }} · {{ contextModal.model }}</p>
          </div>
          <button @click="contextModal.show = false" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div class="p-5 overflow-y-auto space-y-3">
          <div v-if="contextModal.loading" class="text-sm text-gray-400">Загрузка...</div>
          <p v-else-if="contextModal.error" class="text-red-500 text-sm">{{ contextModal.error }}</p>
          <template v-else>
            <div v-if="contextModal.system">
              <div class="text-xs font-semibold text-purple-600 uppercase mb-1">System</div>
              <pre class="whitespace-pre-wrap break-words text-xs bg-purple-50 border border-purple-100 rounded-xl p-3 text-gray-700">{{ contextModal.system }}</pre>
            </div>
            <div v-for="(m, i) in contextModal.messages" :key="i">
              <div :class="['text-xs font-semibold uppercase mb-1', m.role === 'user' ? 'text-brand-600' : 'text-gray-500']">{{ m.role }}</div>
              <pre :class="['whitespace-pre-wrap break-words text-xs rounded-xl p-3 text-gray-700 border', m.role === 'user' ? 'bg-brand-50 border-brand-100' : 'bg-gray-50 border-gray-100']">{{ m.content }}</pre>
            </div>
            <div v-if="!contextModal.system && contextModal.messages.length === 0" class="text-sm text-gray-400">Контекст пуст</div>
          </template>
        </div>
      </div>
    </div>

    <!-- New chat modal -->
    <div v-if="showNewChat" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="showNewChat = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
        <h2 class="text-lg font-semibold mb-4">Новый чат</h2>
        <form @submit.prevent="startChat" class="space-y-3">
          <div>
            <label class="block text-sm font-medium mb-1">VK ID клиента (число) <span class="text-red-500">*</span></label>
            <input
              v-model="newVkUserId"
              required
              autofocus
              type="number"
              placeholder="например: 12345"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Имя клиента (необязательно)</label>
            <input
              v-model="newClientName"
              placeholder="Иван Иванов"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Направление <span class="text-red-500">*</span></label>
            <select
              v-model="newTypeId"
              required
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option v-if="dialogTypes.length === 0" :value="null" disabled>Загрузка...</option>
              <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Метка рекламы (необязательно)</label>
            <input
              v-model="newMarketingTag"
              placeholder="sweetgold, ПАВЕЛ_ПАТРИОТ_1..."
              list="marketing_tag_options"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <datalist id="marketing_tag_options">
              <option v-for="t in knownMarketingTags" :key="t" :value="t" />
            </datalist>
            <p class="text-xs text-gray-400 mt-1">То же, что ref у рекламной ссылки — определяет, какое приветствие получит клиент.</p>
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Модель ИИ</label>
            <select
              v-model="newAiProvider"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white"
            >
              <option value="openai">ChatGPT</option>
              <option value="anthropic">Claude</option>
              <option value="minimax">MiniMax M2.7</option>
              <option value="qwen">Qwen</option>
            </select>
          </div>
          <p v-if="startError" class="text-red-500 text-sm">{{ startError }}</p>
          <div class="flex gap-2 pt-1">
            <button type="submit" :disabled="startLoading || !String(newVkUserId).trim()" class="flex-1 bg-brand-600 text-white py-2 rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50">
              {{ startLoading ? 'Создаём...' : 'Начать чат' }}
            </button>
            <button type="button" @click="showNewChat = false" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">
              Отмена
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import api from '../api'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const dialogs = ref([])
const dialogsOffset = ref(0)
const dialogsHasMore = ref(true)
const dialogsLoading = ref(false)
// Список не загрузился — это не «нет чатов». Молчаливый пустой экран менеджеры
// читали как «диалогов нет» и шли выяснять к нам (Георгий, 17.08).
const dialogsError = ref('')
const dialogsCount = ref(0)
const dialogListEl = ref(null)
const activeDialogId = ref(null)
const messages = ref([])
const pingState = ref(null)
const input = ref('')
const sending = ref(false)
const messagesEl = ref(null)
const fileInput = ref(null)
const pendingFiles = ref([])

const showMenu = ref(false)
const showExportMenu = ref(false)
const showNewChat = ref(false)
const newVkUserId = ref('')
const newClientName = ref('')
const newTypeId = ref(null)
const newAiProvider = ref('qwen')
const newMarketingTag = ref('')
// Метки уже виденных диалогов — подсказка, чтобы тестировщик не угадывал написание.
const knownMarketingTags = computed(() =>
  [...new Set(dialogs.value.flatMap(d => d.marketing_tags || []))].sort()
)
const startLoading = ref(false)
const startError = ref('')

const dialogTypes = ref([])
const statuses = ref([])
const statusChanging = ref(false)

const showDeleteAll = ref(false)
const deleteAllLoading = ref(false)

const showDeleteOne = ref(null)
const deleteOneLoading = ref(false)
const showResetPing = ref(false)
const resetPingLoading = ref(false)

const feedbackModal = ref({ show: false, messageId: null, feedbackId: null, text: '', loading: false, error: '' })

// Готовые причины в один клик. Форма требует 30 символов — правило «плохо» ИИ
// ничему не учит, — но менеджеру, который тушит пожар в диалоге, писать абзац
// некогда, и за месяц работы через эту форму не завели ни одного правила.
// Кнопка подставляет полную формулировку, дописать своё по-прежнему можно.
const feedbackPresets = [
  { label: 'Не то место нанесения', rule: 'Место нанесения указано неверно. Имя по умолчанию наносим на грудь справа, фамилию — на спину вместе с гербом. По центру груди имена и фамилии не печатаем.' },
  { label: 'Повторила цену', rule: 'Цену в этом диалоге клиенту уже называли. Второй раз отправлять прайс не нужно — на возражение отвечаем отработкой, а не повтором стоимости.' },
  { label: 'Не поняла отказ', rule: 'Клиент отказался, а ответ повёл заказ дальше по воронке. На отказе нужно выяснить причину — что именно не подошло, — и не прощаться с клиентом.' },
  { label: 'Ушла от вопроса', rule: 'Клиент задал прямой вопрос, а ответ увёл в сторону. Сначала отвечаем на заданный вопрос, и только потом ведём по следующему шагу воронки.' },
  { label: 'Слишком длинно', rule: 'Ответ слишком длинный для этой реплики. На короткое сообщение клиента отвечаем одним-двумя предложениями и одним вопросом, без пересказа всего заказа.' },
  { label: 'Придумала факт', rule: 'В ответе есть утверждение, которого нет ни в скриптах, ни в товарной матрице. Цены, сроки, наличие и условия берём только оттуда, своего не добавляем.' },
  { label: 'Переспросила уже названное', rule: 'ИИ переспросила то, что клиент уже сообщил в этом диалоге. Собранные данные заказа спрашиваем один раз.' },
]

function openFeedback(msg) {
  feedbackModal.value = {
    show: true,
    messageId: msg.id,
    feedbackId: msg.feedback_id || null,
    text: msg.feedback_text || '',
    loading: false,
    error: '',
  }
}

async function saveFeedback() {
  const fm = feedbackModal.value
  if (!fm.text.trim()) return
  fm.loading = true
  fm.error = ''
  try {
    if (fm.feedbackId) {
      await api.patch(`/feedback/${fm.feedbackId}`, { rule_text: fm.text.trim() })
    } else {
      const res = await api.post(`/feedback/messages/${fm.messageId}`, { rule_text: fm.text.trim() })
      const msg = messages.value.find(m => m.id === fm.messageId)
      if (msg) { msg.feedback_id = res.data.id; msg.feedback_text = res.data.rule_text }
    }
    const msg = messages.value.find(m => m.id === fm.messageId)
    if (msg) msg.feedback_text = fm.text.trim()
    fm.show = false
  } catch (e) {
    fm.error = e.response?.data?.detail || 'Ошибка'
  } finally {
    fm.loading = false
  }
}

async function deleteFeedback() {
  const fm = feedbackModal.value
  if (!fm.feedbackId) return
  fm.loading = true
  fm.error = ''
  try {
    await api.delete(`/feedback/${fm.feedbackId}`)
    const msg = messages.value.find(m => m.id === fm.messageId)
    if (msg) { msg.feedback_id = null; msg.feedback_text = null }
    fm.show = false
  } catch (e) {
    fm.error = e.response?.data?.detail || 'Ошибка'
  } finally {
    fm.loading = false
  }
}

const contextModal = ref({ show: false, loading: false, error: '', provider: '', model: '', system: '', messages: [] })

function normalizeContent(content) {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content.map(b => {
      if (typeof b === 'string') return b
      if (b && typeof b === 'object') {
        if (typeof b.text === 'string') return b.text
        if (b.type) return `[${b.type}]\n${JSON.stringify(b, null, 2)}`
      }
      return JSON.stringify(b, null, 2)
    }).join('\n\n')
  }
  if (content == null) return ''
  return JSON.stringify(content, null, 2)
}

async function openContext(msg) {
  contextModal.value = { show: true, loading: true, error: '', provider: '', model: '', system: '', messages: [] }
  try {
    const res = await api.get(`/chat/run-context/${msg.id}`)
    const fc = res.data.full_context || {}
    contextModal.value.provider = res.data.provider || ''
    contextModal.value.model = res.data.model || ''
    contextModal.value.system = normalizeContent(fc.system)
    contextModal.value.messages = (fc.messages || []).map(m => {
      // Tool calls come back without a `role` (they carry `type` instead) — label
      // them explicitly so they don't render as empty "?" rows.
      if (m.type === 'function_call') {
        return { role: `🔧 ${m.name || 'tool'} (вызов)`, content: normalizeContent(m.arguments) }
      }
      if (m.type === 'function_call_output') {
        return { role: '🔧 результат', content: normalizeContent(m.output) }
      }
      return { role: m.role || '?', content: normalizeContent(m.content) }
    })
  } catch (e) {
    contextModal.value.error = e.response?.data?.detail || 'Ошибка загрузки'
  } finally {
    contextModal.value.loading = false
  }
}

const FILTERS_KEY = 'dialog_filters'

const DATE_PRESETS = [
  { value: 'all', label: 'Все время' },
  { value: 'today', label: 'Сегодня' },
  { value: 'yesterday', label: 'Вчера' },
  { value: 'current_week', label: 'Текущая неделя' },
  { value: 'last_7', label: 'За последние 7 дней' },
  { value: 'last_30', label: 'За последние 30 дней' },
  { value: 'current_month', label: 'Текущий месяц' },
  { value: 'last_month', label: 'Последний месяц' },
  { value: 'custom', label: 'Своя дата' },
]

function getDateRange(preset, customFrom, customTo) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const endOfToday = new Date(startOfToday.getTime() + 86400000 - 1)

  switch (preset) {
    case 'today':
      return { from: startOfToday.toISOString(), to: endOfToday.toISOString() }
    case 'yesterday': {
      const s = new Date(startOfToday.getTime() - 86400000)
      const e = new Date(startOfToday.getTime() - 1)
      return { from: s.toISOString(), to: e.toISOString() }
    }
    case 'current_week': {
      const day = startOfToday.getDay() || 7
      const s = new Date(startOfToday.getTime() - (day - 1) * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_7': {
      const s = new Date(startOfToday.getTime() - 6 * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_30': {
      const s = new Date(startOfToday.getTime() - 29 * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'current_month': {
      const s = new Date(now.getFullYear(), now.getMonth(), 1)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_month': {
      const s = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      const e = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, -1)
      return { from: s.toISOString(), to: e.toISOString() }
    }
    case 'custom': {
      const from = customFrom ? new Date(customFrom).toISOString() : null
      const to = customTo ? new Date(customTo + 'T23:59:59').toISOString() : null
      return { from, to }
    }
    default:
      return { from: null, to: null }
  }
}

// Версия сохранённых фильтров. Выбор «тестовые/реальные» из старых версий
// игнорируем: он записывался туда прежним умолчанием, а не решением менеджера,
// и на новом устройстве панель открывалась пустой.
const FILTERS_VERSION = 2

function loadFiltersFromStorage() {
  try {
    const raw = localStorage.getItem(FILTERS_KEY)
    if (!raw) return null
    const saved = JSON.parse(raw)
    if (saved?.v !== FILTERS_VERSION) {
      delete saved.filterShowTest
      delete saved.filterShowReal
    }
    return saved
  } catch { return null }
}

function saveFiltersToStorage() {
  // Safari в приватном окне бросает на setItem. Фильтры — не та вещь, ради
  // которой стоит ронять открытие диалога: не сохранились и не сохранились.
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify({
    v: FILTERS_VERSION,
    filterShowTest: filterShowTest.value,
    filterShowReal: filterShowReal.value,
    filterStatuses: filterStatuses.value,
    filterDatePreset: filterDatePreset.value,
    filterDateFrom: filterDateFrom.value,
    filterDateTo: filterDateTo.value,
    filterClientId: filterClientId.value,
    filterClientDatePreset: filterClientDatePreset.value,
    filterClientDateFrom: filterClientDateFrom.value,
    filterClientDateTo: filterClientDateTo.value,
    filterAiProviders: filterAiProviders.value,
    filterDialogTypeId: filterDialogTypeId.value,
    filterPingFunnelType: filterPingFunnelType.value,
    filterFunnelStage: filterFunnelStage.value,
      filterLastMessageFrom: filterLastMessageFrom.value,
    }))
  } catch {}
}

const _saved = loadFiltersFromStorage()
const showFilters = ref(false)
// По умолчанию — реальные диалоги: панелью теперь работают менеджеры, и на новом
// устройстве они видели пустой список с фильтром «Тестовые диалоги» («нет
// реальных диалогов», Георгий, 17.08 — и то же самое у второго менеджера).
// Тестовые с кнопкой «+ Новый чат» рядом, в том же селекте: он открывался ради
// них (Женя, Георгий, 30.07), поэтому там же есть «Все диалоги».
const filterShowTest = ref(_saved?.filterShowTest ?? false)
const filterShowReal = ref(_saved?.filterShowReal ?? true)
const filterStatuses = ref(_saved?.filterStatuses ?? [])
const filterDatePreset = ref(_saved?.filterDatePreset ?? 'all')
const filterDateFrom = ref(_saved?.filterDateFrom ?? '')
const filterDateTo = ref(_saved?.filterDateTo ?? '')
const filterClientId = ref(_saved?.filterClientId ?? '')
const filterClientDatePreset = ref(_saved?.filterClientDatePreset ?? 'all')
const filterClientDateFrom = ref(_saved?.filterClientDateFrom ?? '')
const filterClientDateTo = ref(_saved?.filterClientDateTo ?? '')
const filterAiProviders = ref(_saved?.filterAiProviders ?? [])
const filterDialogTypeId = ref(_saved?.filterDialogTypeId ?? null)
const filterPingFunnelType = ref(_saved?.filterPingFunnelType ?? null)
const filterFunnelStage = ref(_saved?.filterFunnelStage ?? null)
const filterLastMessageFrom = ref(_saved?.filterLastMessageFrom ?? '')
const pingFunnelTypes = ref([])
const showDateDropdown = ref(false)
const showClientDateDropdown = ref(false)
const csvExporting = ref(false)
const idsExporting = ref(false)
const idsCopied = ref(false)

const activeDialog = computed(() => dialogs.value.find(d => d.id === activeDialogId.value))
const activeStatuses = computed(() => statuses.value.filter(s => s.is_active))

// Все статусы + вариант «Без статуса»
const allStatusValues = computed(() => [...activeStatuses.value.map(s => s.name), '__none__'])
const allStatusesSelected = computed(() =>
  allStatusValues.value.every(v => filterStatuses.value.includes(v))
)
function toggleAllStatuses() {
  filterStatuses.value = allStatusesSelected.value ? [] : [...allStatusValues.value]
}

// Стадия воронки (FunnelAgent) → человекочитаемый ярлык. Ключи совпадают с STAGE_LABELS бэка.
const FUNNEL_STAGE_LABELS = {
  greeting: 'Приветствие',
  format: 'Формат',
  calculation: 'Расчёт',
  timing: 'Сроки',
  photo: 'Фото',
  contacts: 'Контакты',
  prepayment: 'Предоплата',
  paid: 'Оплачено',
}
function funnelStageLabel(stage) {
  return FUNNEL_STAGE_LABELS[stage] || stage
}
const isAdmin = computed(() => auth.user?.role === 'admin')
const isCurator = computed(() => auth.user?.role === 'curator')
// Пока профиль не пришёл, роль неизвестна — и прятать от пользователя реальные
// диалоги на этом основании нельзя: именно так панель открывалась пустой, с
// единственным пунктом «Тестовые диалоги» (Георгий, 17.08). Доступ всё равно
// решает сервер: /chat/dialogs пускает только админа и куратора.
const canSeeRealDialogs = computed(() => !auth.ready || !auth.user || isAdmin.value || isCurator.value)
const hasActiveFilters = computed(() => filterShowTest.value || !filterShowReal.value || filterStatuses.value.length > 0 || filterDatePreset.value !== 'all' || filterClientId.value.trim() !== '' || filterClientDatePreset.value !== 'all' || filterAiProviders.value.length > 0 || filterDialogTypeId.value !== null || filterPingFunnelType.value !== null || filterFunnelStage.value !== null || filterLastMessageFrom.value !== '')
const dialogTypeFilterValue = computed(() => {
  if (filterShowTest.value && filterShowReal.value) return 'all'
  if (filterShowReal.value) return 'real'
  return 'test'
})
function setDialogTypeFilter(val) {
  if (val === 'all') { filterShowTest.value = true; filterShowReal.value = true }
  else if (val === 'real') { filterShowTest.value = false; filterShowReal.value = true }
  else { filterShowTest.value = true; filterShowReal.value = false }
}
const selectedDateLabel = computed(() => DATE_PRESETS.find(p => p.value === filterDatePreset.value)?.label ?? 'Все время')
const selectedClientDateLabel = computed(() => DATE_PRESETS.find(p => p.value === filterClientDatePreset.value)?.label ?? 'Все время')

const STATUS_COLORS = {
  // Не brand-*: бейджи статусов должны отличаться друг от друга при любой теме,
  // а «Заказ оформлен» ниже уже зелёный — фирменный зелёный слился бы с ним.
  'Поинтересовался':  'bg-blue-100 text-blue-700',
  'Есть расчет':      'bg-purple-100 text-purple-700',
  'Горячий':          'bg-red-100 text-red-700',
  'Ждем предоплату':  'bg-yellow-100 text-yellow-800',
  'Заказ оформлен':   'bg-green-100 text-green-700',
  'Нужен куратор':    'bg-orange-100 text-orange-700',
  'Спам':             'bg-gray-100 text-gray-500',
}

function statusColor(name) {
  return STATUS_COLORS[name] || 'bg-gray-100 text-gray-600'
}

function buildDialogParams(offset = 0) {
  const params = new URLSearchParams()
  if (filterShowTest.value && !filterShowReal.value) params.append('is_test', 'true')
  else if (!filterShowTest.value && filterShowReal.value) params.append('is_test', 'false')
  for (const s of filterStatuses.value) params.append('status_filter', s)
  for (const p of filterAiProviders.value) params.append('ai_provider_filter', p)
  if (filterDialogTypeId.value !== null) params.append('dialog_type_ids', filterDialogTypeId.value)
  if (filterPingFunnelType.value !== null) params.append('ping_funnel_type', filterPingFunnelType.value)
  if (filterFunnelStage.value !== null) params.append('funnel_stage', filterFunnelStage.value)
  if (filterLastMessageFrom.value) params.append('last_message_from', filterLastMessageFrom.value)
  if (filterClientId.value.trim()) params.append('vk_user_id', filterClientId.value.trim())
  const { from, to } = getDateRange(filterDatePreset.value, filterDateFrom.value, filterDateTo.value)
  if (from) params.append('date_from', from)
  if (to) params.append('date_to', to)
  const { from: clientFrom, to: clientTo } = getDateRange(filterClientDatePreset.value, filterClientDateFrom.value, filterClientDateTo.value)
  if (clientFrom) params.append('client_date_from', clientFrom)
  if (clientTo) params.append('client_date_to', clientTo)
  params.append('offset', offset)
  return params
}

async function loadDialogs() {
  if (!filterShowTest.value && !filterShowReal.value) {
    dialogs.value = []
    dialogsOffset.value = 0
    dialogsHasMore.value = false
    dialogsCount.value = 0
    return
  }
  dialogsOffset.value = 0
  dialogsHasMore.value = true
  dialogsLoading.value = true
  dialogsError.value = ''
  try {
    const res = await api.get('/chat/dialogs', { params: buildDialogParams(0) })
    dialogs.value = res.data
    dialogsHasMore.value = res.data.length === 50
    dialogsOffset.value = res.data.length
    api.get('/chat/dialogs/count', { params: buildDialogParams(0) })
      .then(r => { dialogsCount.value = r.data.count })
      .catch(() => {})
  } catch (e) {
    dialogs.value = []
    dialogsCount.value = 0
    dialogsHasMore.value = false
    dialogsError.value = e.response?.status === 403
      ? 'Нет доступа к направлению диалогов — попросите админа выдать его в разделе «Пользователи».'
      : 'Не удалось загрузить диалоги.'
  } finally {
    dialogsLoading.value = false
  }
}

async function loadMoreDialogs() {
  if (!dialogsHasMore.value || dialogsLoading.value) return
  dialogsLoading.value = true
  try {
    const res = await api.get('/chat/dialogs', { params: buildDialogParams(dialogsOffset.value) })
    dialogs.value = [...dialogs.value, ...res.data]
    dialogsHasMore.value = res.data.length === 50
    dialogsOffset.value += res.data.length
  } finally {
    dialogsLoading.value = false
  }
}

function onDialogListScroll(e) {
  const el = e.target
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 150) {
    loadMoreDialogs()
  }
}

async function applyFilters() {
  saveFiltersToStorage()
  showFilters.value = false
  await loadDialogs()
  if (activeDialogId.value) {
    const stillVisible = dialogs.value.find(d => d.id === activeDialogId.value)
    if (!stillVisible) { activeDialogId.value = null; messages.value = [] }
  }
}

function resetFilters() {
  filterShowTest.value = false
  filterShowReal.value = true
  filterStatuses.value = []
  filterDatePreset.value = 'all'
  filterDateFrom.value = ''
  filterDateTo.value = ''
  filterClientId.value = ''
  filterClientDatePreset.value = 'all'
  filterClientDateFrom.value = ''
  filterClientDateTo.value = ''
  filterAiProviders.value = []
  filterDialogTypeId.value = null
  filterPingFunnelType.value = null
  filterFunnelStage.value = null
  filterLastMessageFrom.value = ''
  applyFilters()
}

function buildExportParams() {
  const params = new URLSearchParams()
  if (filterShowTest.value && !filterShowReal.value) params.append('is_test', 'true')
  else if (!filterShowTest.value && filterShowReal.value) params.append('is_test', 'false')
  for (const s of filterStatuses.value) params.append('status_filter', s)
  for (const p of filterAiProviders.value) params.append('ai_provider_filter', p)
  if (filterDialogTypeId.value !== null) params.append('dialog_type_ids', filterDialogTypeId.value)
  if (filterPingFunnelType.value !== null) params.append('ping_funnel_type', filterPingFunnelType.value)
  if (filterFunnelStage.value !== null) params.append('funnel_stage', filterFunnelStage.value)
  if (filterLastMessageFrom.value) params.append('last_message_from', filterLastMessageFrom.value)
  if (filterClientId.value.trim()) params.append('vk_user_id', filterClientId.value.trim())
  const { from, to } = getDateRange(filterDatePreset.value, filterDateFrom.value, filterDateTo.value)
  if (from) params.append('date_from', from)
  if (to) params.append('date_to', to)
  const { from: clientFrom, to: clientTo } = getDateRange(filterClientDatePreset.value, filterClientDateFrom.value, filterClientDateTo.value)
  if (clientFrom) params.append('client_date_from', clientFrom)
  if (clientTo) params.append('client_date_to', clientTo)
  return params
}

function downloadBlob(res, fallbackName) {
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  const cd = res.headers['content-disposition'] || ''
  const match = cd.match(/filename=(.+)/)
  a.download = match ? match[1] : fallbackName
  a.click()
  URL.revokeObjectURL(url)
}

async function exportDialogsCsv() {
  csvExporting.value = true
  try {
    const res = await api.get('/chat/dialogs/export', { params: buildExportParams(), responseType: 'blob' })
    downloadBlob(res, 'dialogs.csv')
  } finally {
    csvExporting.value = false
  }
}

async function exportClientIds() {
  idsExporting.value = true
  try {
    const res = await api.get('/chat/dialogs/export-ids', { params: buildExportParams() })
    await navigator.clipboard.writeText(res.data || '')
    idsCopied.value = true
    setTimeout(() => { idsCopied.value = false }, 2000)
  } finally {
    idsExporting.value = false
  }
}

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function roleLabel(msg) {
  if (msg.role === 'client') return 'Клиент'
  if (msg.role === 'curator') return '👤 Оператор (ВК)'
  if (msg.role === 'ai' && msg.is_ping) return '🔔 Пинг'
  if (msg.role === 'ai') return '🤖 AI'
  return msg.role || ''
}

function exportDialogHtml() {
  const d = activeDialog.value
  if (!d) return
  const title = `Диалог ${d.vk_user_id || activeDialogId.value}`

  const rows = messages.value.map(msg => {
    const side = msg.role === 'client' ? 'right' : 'left'
    const cls = msg.role === 'client' ? 'client' : (msg.role === 'curator' ? 'curator' : (msg.is_ping ? 'ping' : 'ai'))
    const meta = []
    if (msg.confidence_score !== null && msg.confidence_score !== undefined && msg.role !== 'client') {
      meta.push(`${(msg.confidence_score * 100).toFixed(0)}% уверенность`)
    }
    if (msg.need_curator) {
      meta.push('⚠ На проверку куратору' + (msg.curator_trigger ? `: ${escapeHtml(msg.curator_trigger)}` : ''))
    }
    if (msg.selected_script) meta.push(escapeHtml(msg.selected_script))

    const files = (msg.files || []).map(url => isAudioUrl(url)
      ? `<audio src="${escapeHtml(url)}" controls></audio>`
      : `<img src="${escapeHtml(url)}" loading="lazy" />`).join('')
    const audios = (msg.audio_urls || []).map(url => `<audio src="${escapeHtml(url)}" controls></audio>`).join('')

    return `<div class="row ${side}">
  <div class="bubble ${cls}">
    <div class="label">${escapeHtml(roleLabel(msg))}</div>
    <div class="text">${escapeHtml(msg.text)}</div>
    ${files ? `<div class="media">${files}</div>` : ''}
    ${audios ? `<div class="media">${audios}</div>` : ''}
    ${meta.length ? `<div class="meta">${meta.join(' · ')}</div>` : ''}
    ${msg.created_at ? `<div class="time">${escapeHtml(formatMsgTime(msg.created_at))}</div>` : ''}
  </div>
</div>`
  }).join('\n')

  const html = `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; background: #f3f4f6; margin: 0; padding: 24px; color: #1f2937; }
  .wrap { max-width: 760px; margin: 0 auto; }
  header { background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 16px 20px; margin-bottom: 16px; }
  header h1 { font-size: 18px; margin: 0 0 4px; }
  header .sub { font-size: 13px; color: #6b7280; }
  .row { display: flex; margin: 10px 0; }
  .row.right { justify-content: flex-end; }
  .row.left { justify-content: flex-start; }
  .bubble { max-width: 78%; padding: 10px 14px; border-radius: 16px; font-size: 14px; box-shadow: 0 1px 2px rgba(0,0,0,.05); }
  .bubble.client { background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
  .bubble.ai { background: #fff; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
  .bubble.curator { background: #faf5ff; border: 1px solid #e9d5ff; border-bottom-left-radius: 4px; }
  .bubble.ping { background: #fffbeb; border: 1px solid #fde68a; border-bottom-left-radius: 4px; }
  .label { font-size: 11px; font-weight: 600; opacity: .8; margin-bottom: 3px; }
  .text { white-space: pre-wrap; line-height: 1.5; }
  .media { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
  .media img { max-width: 100%; max-height: 280px; border-radius: 8px; object-fit: contain; }
  .media audio { width: 100%; max-width: 320px; }
  .meta { font-size: 11px; color: #9ca3af; margin-top: 4px; }
  .bubble.client .meta { color: #bfdbfe; }
  .time { font-size: 11px; color: #9ca3af; margin-top: 2px; text-align: right; }
  .bubble.client .time { color: #bfdbfe; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>${escapeHtml(title)}</h1>
    <div class="sub">
      ${d.client_name && String(d.client_name) !== String(d.vk_user_id) ? escapeHtml(d.client_name) + ' · ' : ''}Dialog #${escapeHtml(activeDialogId.value)}${d.current_status ? ' · ' + escapeHtml(d.current_status) : ''}
    </div>
  </header>
  ${rows}
</div>
</body>
</html>`

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `dialog_${d.vk_user_id || activeDialogId.value}.html`
  a.click()
  URL.revokeObjectURL(url)
}

async function loadDialogTypes() {
  try {
    const res = await api.get('/dialog-types/')
    dialogTypes.value = res.data
    if (res.data.length > 0 && newTypeId.value === null) {
      newTypeId.value = res.data[0].id
    }
  } catch {}
}

async function loadPingFunnelTypes() {
  try {
    const res = await api.get('/chat/ping-funnel-types')
    pingFunnelTypes.value = res.data
  } catch {}
}

async function loadStatuses() {
  try {
    const res = await api.get('/dialog_statuses/')
    statuses.value = res.data
  } catch {}
}

// Счётчик открытий чата. Запросы истории летят параллельно и возвращаются в
// произвольном порядке: без него быстрое переключение А → Б заканчивалось тем,
// что подоспевший позже ответ по А затирал переписку Б. То же и с опросом раз в
// 10 секунд, и с отправкой (ответ ИИ идёт 10-20 сек — за это время куратор
// успевает уйти в другой чат, и реплики прилетали не туда).
let _openSeq = 0

async function openDialog(id) {
  const seq = ++_openSeq
  activeDialogId.value = id
  pingState.value = null
  messages.value = []
  const dialog = dialogs.value.find(d => d.id === id)
  aiPaused.value = dialog?.ai_paused ?? false
  vkBlocked.value = false
  const res = await api.get(`/chat/${id}/history`)
  if (seq !== _openSeq) return  // за время запроса открыли другой чат
  messages.value = res.data
  await scrollBottom()
  try {
    const dRes = await api.get(`/dialogs/${id}`)
    if (seq !== _openSeq) return
    pingState.value = dRes.data.ping_state
    aiPaused.value = dRes.data.ai_paused ?? false
    vkBlocked.value = dRes.data.vk_blocked ?? false
    paymentConfirmed.value = Boolean(dRes.data.payment_confirmed_at)
  } catch {}
}

const aiPaused = ref(false)
const vkBlocked = ref(false)
const aiPauseLoading = ref(false)

// Пауза ставится автоматически, когда живой оператор отвечает из ВК; здесь куратор снимает/ставит её вручную.
async function toggleAiPause(paused) {
  const dialogId = activeDialogId.value
  if (!dialogId) return
  aiPauseLoading.value = true
  try {
    const res = await api.post(`/dialogs/${dialogId}/ai-pause`, { paused })
    const d = dialogs.value.find(d => d.id === dialogId)
    if (d) d.ai_paused = res.data.ai_paused
    if (activeDialogId.value === dialogId) aiPaused.value = res.data.ai_paused
  } catch (e) {
    alert('Ошибка: ' + (e.response?.data?.detail || e.message))
  } finally {
    aiPauseLoading.value = false
  }
}

async function changeStatus(newStatusName) {
  const dialogId = activeDialogId.value
  if (!dialogId || !newStatusName) return
  statusChanging.value = true
  try {
    await api.post(`/dialogs/${dialogId}/status`, { new_status: newStatusName })
    const d = dialogs.value.find(d => d.id === dialogId)
    if (d) d.current_status = newStatusName
  } catch (e) {
    alert('Ошибка: ' + (e.response?.data?.detail || e.message))
  } finally {
    statusChanging.value = false
  }
}

async function startChat() {
  startError.value = ''
  startLoading.value = true
  try {
    const res = await api.post('/chat/start', {
      vk_user_id: Number(newVkUserId.value),
      client_name: newClientName.value.trim() || null,
      type_id: newTypeId.value,
      ai_provider: newAiProvider.value,
      marketing_tag: newMarketingTag.value.trim() || null,
    })
    showNewChat.value = false
    newVkUserId.value = ''
    newClientName.value = ''
    newTypeId.value = dialogTypes.value[0]?.id ?? null
    newAiProvider.value = 'qwen'
    newMarketingTag.value = ''
    // Созданный чат всегда тестовый: если фильтр стоит на реальных, он бы
    // не появился в списке и выглядел бы как «не создался».
    if (!filterShowTest.value) {
      filterShowTest.value = true
      filterShowReal.value = false
    }
    await loadDialogs()
    await openDialog(res.data.dialog_id)
  } catch (e) {
    startError.value = e.response?.data?.detail || 'Ошибка'
  } finally {
    startLoading.value = false
  }
}

function removeFile(index) {
  URL.revokeObjectURL(pendingFiles.value[index].preview)
  pendingFiles.value.splice(index, 1)
}

async function onFilesSelected(e) {
  const files = Array.from(e.target.files)
  e.target.value = ''
  // Фиксируем чат на момент выбора файлов: загрузка идёт по одному, и без этого
  // вложение уходило бы в тот диалог, который открыт к моменту ответа сервера.
  const dialogId = activeDialogId.value
  for (const file of files) {
    const preview = URL.createObjectURL(file)
    const idx = pendingFiles.value.length
    pendingFiles.value.push({ file, preview, url: null, uploading: true })
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.post(`/chat/${dialogId}/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      pendingFiles.value[idx].url = res.data.url
    } catch (err) {
      alert('Ошибка загрузки: ' + (err.response?.data?.detail || err.message))
      URL.revokeObjectURL(preview)
      pendingFiles.value.splice(idx, 1)
    } finally {
      if (pendingFiles.value[idx]) pendingFiles.value[idx].uploading = false
    }
  }
}

async function sendMessage() {
  const text = input.value.trim()
  const files = pendingFiles.value.filter(f => f.url).map(f => f.url)
  if ((!text && !files.length) || sending.value) return

  messages.value.push({
    id: Date.now(), role: 'client',
    text: text || '[фото]',
    files,
    need_curator: false, confidence_score: null,
    created_at: new Date().toISOString(),
  })
  for (const f of pendingFiles.value) URL.revokeObjectURL(f.preview)
  pendingFiles.value = []
  input.value = ''
  sending.value = true
  await scrollBottom()

  const seq = _openSeq
  const dialogId = activeDialogId.value
  try {
    const res = await api.post(`/chat/${dialogId}/message`, { text: text || '[фото]', files })
    if (seq !== _openSeq) return  // ушли в другой чат, пока ИИ думал
    for (const msg of res.data) {
      if (msg.role !== 'client') messages.value.push(msg)
    }
    await loadDialogs()
  } catch (e) {
    if (seq !== _openSeq) return
    messages.value.push({
      id: Date.now(), role: 'ai',
      text: 'Ошибка: ' + (e.response?.data?.detail || e.message),
      files: [], need_curator: false, confidence_score: null,
      created_at: new Date().toISOString(),
    })
  } finally {
    sending.value = false
    await scrollBottom()
  }
}

// Имя и фамилия клиента из профиля ВК. В списке лидов первой строкой стоял
// числовой VK ID, а имя пряталось строкой ниже: «имя фамилия надо вывести в
// лидах вместо айди» (ОП, 10 августа, 16:16). ID остаётся второй строкой — по
// нему ищут диалог в фильтрах.
function fullName(d) {
  if (!d) return ''
  const parts = [d.client_name, d.client_last_name].filter(Boolean).map(String)
  // У тестовых чатов в имя кладут сам VK ID — тогда это не имя.
  if (parts.length === 1 && parts[0] === String(d.vk_user_id)) return ''
  return parts.join(' ').trim()
}

function leadTitle(d) {
  return fullName(d) || (d?.vk_user_id ? String(d.vk_user_id) : '—')
}

const paymentConfirmed = ref(false)
const confirmingPayment = ref(false)

async function togglePaymentConfirmed() {
  // Платёжной интеграции нет — счёт выставляет человек, значит и подтвердить
  // оплату может только он. До отметки ИИ не видит шагов «после оплаты».
  const dialogId = activeDialogId.value
  confirmingPayment.value = true
  try {
    const res = await api.post(`/dialogs/${dialogId}/payment-confirmed`, {
      confirmed: !paymentConfirmed.value,
    })
    paymentConfirmed.value = Boolean(res.data.payment_confirmed_at)
  } catch (e) {
    managerError.value = e.response?.data?.detail || e.message
  } finally {
    confirmingPayment.value = false
  }
}

const managerInput = ref('')
const sendingManager = ref(false)
const managerError = ref('')

// Вложения менеджера: грузим на наш сервер, отправляем ссылками — бэкенд
// превратит их в токены, а отправка перезальёт во ВК (просьба ОП от 18.08:
// «отправку фото и видео из панельки тоже добавить»).
const managerFiles = ref([])
const managerFileInput = ref(null)

function removeManagerFile(index) {
  const f = managerFiles.value[index]
  if (f?.preview) URL.revokeObjectURL(f.preview)
  managerFiles.value.splice(index, 1)
}

async function onManagerFilesSelected(e) {
  const files = Array.from(e.target.files)
  e.target.value = ''
  const dialogId = activeDialogId.value
  for (const file of files) {
    const preview = file.type.startsWith('image/') ? URL.createObjectURL(file) : null
    const idx = managerFiles.value.length
    managerFiles.value.push({ name: file.name, preview, url: null, uploading: true })
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.post(`/chat/${dialogId}/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120_000,
      })
      if (managerFiles.value[idx]) managerFiles.value[idx].url = res.data.url
    } catch (err) {
      managerError.value = `${file.name}: ${err.response?.data?.detail || 'не загрузилось'}`
      if (preview) URL.revokeObjectURL(preview)
      managerFiles.value.splice(idx, 1)
      continue
    } finally {
      if (managerFiles.value[idx]) managerFiles.value[idx].uploading = false
    }
  }
}

async function sendAsManager() {
  const text = managerInput.value.trim()
  const files = managerFiles.value.filter(f => f.url).map(f => f.url)
  if ((!text && !files.length) || sendingManager.value) return

  sendingManager.value = true
  managerError.value = ''
  const seq = _openSeq
  const dialogId = activeDialogId.value
  try {
    const res = await api.post(`/chat/${dialogId}/reply`, { text, files })
    if (seq !== _openSeq) return
    messages.value.push(res.data)
    managerInput.value = ''
    for (const f of managerFiles.value) if (f.preview) URL.revokeObjectURL(f.preview)
    managerFiles.value = []
    // Отправка сама ставит ИИ на паузу — отражаем это в тумблере, не перезагружая чат.
    aiPaused.value = true
    const d = dialogs.value.find(x => x.id === dialogId)
    if (d) d.ai_paused = true
    await scrollBottom()
  } catch (e) {
    if (seq !== _openSeq) return
    managerError.value = e.response?.data?.detail || e.message
  } finally {
    sendingManager.value = false
  }
}

async function deleteAllChats() {
  deleteAllLoading.value = true
  try {
    await api.delete('/chat/dialogs')
    dialogs.value = []
    activeDialogId.value = null
    messages.value = []
    showDeleteAll.value = false
  } finally {
    deleteAllLoading.value = false
  }
}

async function deleteDialog(id) {
  deleteOneLoading.value = true
  try {
    await api.delete(`/chat/${id}`)
    dialogs.value = dialogs.value.filter(d => d.id !== id)
    if (activeDialogId.value === id) {
      activeDialogId.value = null
      messages.value = []
    }
    showDeleteOne.value = null
  } finally {
    deleteOneLoading.value = false
  }
}

async function resetPingState() {
  const dialogId = activeDialogId.value
  if (!dialogId) return
  resetPingLoading.value = true
  try {
    await api.delete(`/dialogs/${dialogId}/ping-state`)
    if (activeDialogId.value === dialogId) pingState.value = null
    showResetPing.value = false
  } finally {
    resetPingLoading.value = false
  }
}

async function scrollBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function isAudioUrl(url) {
  const lower = (url || '').toLowerCase().split('?')[0]
  return ['.mp3', '.ogg', '.wav', '.m4a', '.aac', '.oga', '.opus', '.flac'].some(ext => lower.endsWith(ext))
}

// Разбирает текст фразы на сегменты текст/фото для красивого отображения в
// тестовом чате: "[photo-<url>]" -> реальная картинка, "[photo/video/audio_message-
// <id>_<id>]" (чужой VK ID без прямой ссылки, см. app/vk/sender.py) -> плейсхолдер.
const ATTACHMENT_TOKEN_RE = /\[(photo|video|clip|audio_message)-([^\]]+)\]/g

// Ссылка целиком: «https://vkvideo.ru/video-44440184_456240651».
const VK_VIDEO_URL_RE = /(?:video|clip)(-?\d+)_(\d+)/
// Голый VK-ID: из токена «[video-44440184_456240651]» сюда приходит только
// «44440184_456240651» — префикс вместе с минусом уже съеден при разборе токена.
// Минус принадлежит владельцу-сообществу, поэтому возвращаем его на место.
const VK_VIDEO_BARE_RE = /^(\d+)_(\d+)$/

// Встроенный плеер ВК. Ролик открывается прямо в панели, не уводя из диалога.
function vkVideoEmbed(payload) {
  const raw = (payload || '').trim()
  const m = VK_VIDEO_URL_RE.exec(raw) || VK_VIDEO_BARE_RE.exec(raw)
  if (!m) return null
  const [, rawOwner, id] = m
  const owner = rawOwner.startsWith('-') ? rawOwner : `-${rawOwner}`
  return {
    embed: `https://vk.com/video_ext.php?oid=${owner}&id=${id}&hd=2`,
    href: /^https?:\/\//i.test(raw) ? raw : `https://vkvideo.ru/video${owner}_${id}`,
  }
}

function parseMessageParts(text) {
  const parts = []
  let lastIndex = 0
  let match
  ATTACHMENT_TOKEN_RE.lastIndex = 0
  while ((match = ATTACHMENT_TOKEN_RE.exec(text || '')) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) })
    }
    const [, kind, payload] = match
    const video = (kind === 'video' || kind === 'clip') ? vkVideoEmbed(payload) : null
    if (video) {
      parts.push({ type: 'video', ...video })
    } else if (/^https?:\/\//i.test(payload)) {
      parts.push({ type: kind === 'photo' ? 'image' : 'link', value: payload })
    } else {
      const label = kind === 'photo' ? '📷 фото'
        : (kind === 'video' || kind === 'clip') ? '🎬 видео'
          : '🎤 голосовое'
      parts.push({ type: 'placeholder', value: label })
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < (text || '').length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) })
  }
  return parts.filter(p => p.type !== 'text' || p.value.trim())
}

// Открытое в модалке вложение: {type:'video', embed, href} или {type:'image', src}.
const preview = ref(null)

function formatDate(d) {
  if (!d) return ''
  const date = new Date(d)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function formatFullDateTime(d) {
  if (!d) return '—'
  const date = new Date(d)
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }) +
    ', ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function formatMsgTime(d) {
  if (!d) return ''
  const date = new Date(d)
  const now = new Date()
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (date.toDateString() === now.toDateString()) return time
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) + ', ' + time
}

let _pollInterval = null

async function pollTick() {
  const seq = _openSeq
  const dialogId = activeDialogId.value
  await loadDialogs()
  if (dialogId && seq === _openSeq && activeDialogId.value === dialogId) {
    const d = dialogs.value.find(d => d.id === dialogId)
    if (d && d.ai_paused !== undefined) aiPaused.value = d.ai_paused
    try {
      const el = messagesEl.value
      const atBottom = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 60
      const res = await api.get(`/chat/${dialogId}/history`)
      if (seq !== _openSeq || activeDialogId.value !== dialogId) return
      messages.value = res.data
      if (atBottom) await scrollBottom()
    } catch {}
  }
}

// Глубокая ссылка: /?vk_user_id=12345 — сбросить фильтры, показать
// диалоги этого клиента и сразу открыть самый свежий.
async function openByVkUserId(vkId) {
  filterShowTest.value = true
  filterShowReal.value = canSeeRealDialogs.value
  filterStatuses.value = []
  filterDatePreset.value = 'all'
  filterDateFrom.value = ''
  filterDateTo.value = ''
  filterClientDatePreset.value = 'all'
  filterClientDateFrom.value = ''
  filterClientDateTo.value = ''
  filterAiProviders.value = []
  filterDialogTypeId.value = null
  filterPingFunnelType.value = null
  filterFunnelStage.value = null
  filterLastMessageFrom.value = ''
  filterClientId.value = vkId
  saveFiltersToStorage()
  await loadDialogs()
  if (dialogs.value.length) await openDialog(dialogs.value[0].id)
  // Убираем query из URL, чтобы перезагрузка/повторный переход не навязывал фильтр.
  router.replace({ path: '/' })
}

onMounted(async () => {
  const vkId = (route.query.vk_user_id || '').toString().trim()
  await Promise.all([loadDialogTypes(), loadStatuses(), loadPingFunnelTypes()])
  if (vkId) {
    await openByVkUserId(vkId)
  } else {
    await loadDialogs()
  }
  _pollInterval = setInterval(pollTick, 10_000)
})

function openPingReview() {
  window.open('/ping-review', '_blank')
}

onUnmounted(() => {
  clearInterval(_pollInterval)
})
</script>
