<template>
  <div class="chat-page">
    <!-- Header bar -->
    <header class="chat-header">
      <el-icon :size="20" color="#0d9488"><Service /></el-icon>
      <span class="chat-header-title">ScopeGraph 范畴图谱</span>
      <el-tag type="success" size="small" effect="plain" class="status-tag">
        在线
      </el-tag>
    </header>

    <!-- Escalation notice (transfer to human agent) -->
    <div v-if="escalationNotice" class="escalation-banner">
      <el-icon :size="16"><Bell /></el-icon>
      <span>{{ escalationNotice }}</span>
    </div>

    <!-- Message list -->
    <div ref="messageListRef" class="message-list">
      <template v-for="msg in chatStore.messages" :key="msg.id">
        <MessageBubble
          :role="msg.role"
          :content="msg.content"
          :status="msg.isStreaming ? 'thinking…' : ''"
        />
        <div v-if="msg.confirmation" class="confirmation-wrapper">
          <ConfirmationCard
            :title="confirmationTitle(msg.confirmation)"
            :body="msg.confirmation.summary"
            :options="confirmationOptions"
            @select="(value: string) => chatStore.respondToConfirmation(msg.confirmation!.operationId, value as 'confirm' | 'cancel')"
          />
        </div>
        <div v-if="msg.escalation" class="escalation-inline">
          <el-alert
            :title="`已转接人工碳合规顾问：${msg.escalation.reason}`"
            type="warning"
            :closable="false"
            show-icon
          >
            <template v-if="msg.escalation.queuePosition" #default>
              当前排队位置：第 {{ msg.escalation.queuePosition }} 位
            </template>
          </el-alert>
        </div>
      </template>
    </div>

    <!-- Status indicator -->
    <div v-if="chatStore.statusText" class="status-bar">
      <el-icon class="status-spinner" :size="14"><Loading /></el-icon>
      <span>{{ chatStore.statusText }}</span>
    </div>

    <!-- Input area -->
    <div class="chat-input-area">
      <div class="input-row">
        <el-upload
          action="/api/chat/upload"
          :headers="uploadHeaders"
          :show-file-list="false"
          :before-upload="beforeUpload"
          :on-success="handleUploadSuccess"
          class="upload-trigger"
        >
          <el-button :icon="Paperclip" circle />
        </el-upload>

        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="试试：化工企业A 2022 年 Scope1 排放是多少？/ 化工企业D 2019 vs 2023 直接排放变化"
          resize="none"
          class="chat-input"
          @keydown.enter.exact.prevent="handleSend"
        />

        <el-button
          type="primary"
          :icon="Promotion"
          circle
          :disabled="!inputText.trim() || chatStore.isLoading"
          @click="handleSend"
        />
      </div>

      <p class="input-hint">按 Enter 发送，Shift + Enter 换行</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Service,
  Promotion,
  Paperclip,
  Bell,
  Loading,
} from '@element-plus/icons-vue'
import type { UploadRawFile } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import MessageBubble from '@/components/MessageBubble.vue'
import ConfirmationCard from '@/components/ConfirmationCard.vue'
import type { ConfirmationPayload } from '@/types'

const authStore = useAuthStore()
const chatStore = useChatStore()

const inputText = ref('')
const messageListRef = ref<HTMLDivElement | null>(null)

const confirmationOptions = [
  { label: '确认', value: 'confirm' },
  { label: '取消', value: 'cancel' },
]

function confirmationTitle(c: ConfirmationPayload): string {
  switch (c.status) {
    case 'confirmed':
      return '操作已确认'
    case 'cancelled':
      return '操作已取消'
    case 'expired':
      return '操作已过期'
    default:
      return '操作确认'
  }
}

onMounted(() => {
  if (chatStore.messages.length === 0) {
    chatStore.newSession()
  }
})

const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${authStore.token}`,
}))

const escalationNotice = computed(() => {
  const last = [...chatStore.messages].reverse().find((m) => m.escalation)
  if (!last?.escalation) return ''
  return `正在为您转接人工碳合规顾问 — ${last.escalation.reason}`
})

watch(
  () => chatStore.messages.length,
  async () => {
    await nextTick()
    scrollToBottom()
  },
)

watch(
  () => {
    const msgs = chatStore.messages
    const last = msgs[msgs.length - 1]
    return last?.content?.length ?? 0
  },
  async () => {
    await nextTick()
    scrollToBottom()
  },
)

function handleSend() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''
  chatStore.sendMessage(text)
}

function scrollToBottom() {
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

function beforeUpload(file: UploadRawFile) {
  const isLt10M = file.size / 1024 / 1024 < 10
  if (!isLt10M) {
    ElMessage.warning('文件大小不能超过 10 MB')
  }
  return isLt10M
}

function handleUploadSuccess(response: { url?: string; message?: string; image_path?: string | null; file_path?: string | null }) {
  if (response.url) {
    ElMessage.success('文件上传成功')
    chatStore.setPendingAttachment({
      imagePath: response.image_path || undefined,
      filePath: response.file_path || undefined,
    })
    inputText.value += `[文件: ${response.url}] `
  } else {
    ElMessage.info(response.message || '上传完成')
  }
}
</script>

<style scoped>
.chat-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #f5f7fa;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.chat-header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.status-tag { margin-left: 4px; }

.escalation-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 24px;
  background: #fdf6ec;
  color: #e6a23c;
  font-size: 13px;
  border-bottom: 1px solid #faecd8;
  flex-shrink: 0;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 24px 12px;
}

.confirmation-wrapper {
  display: flex;
  margin-bottom: 18px;
  padding-left: 46px;
}

.escalation-inline {
  margin-bottom: 18px;
  padding-left: 46px;
  max-width: 70%;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 24px;
  background: #ecfdf5;
  color: #0d9488;
  font-size: 13px;
  border-top: 1px solid #d1fae5;
  flex-shrink: 0;
}

.status-spinner { animation: spin 1s linear infinite; }
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.chat-input-area {
  padding: 12px 24px 16px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.upload-trigger { flex-shrink: 0; }

.chat-input { flex: 1; }
.chat-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.5;
  box-shadow: none;
}

.input-hint {
  margin-top: 6px;
  font-size: 11px;
  color: #c0c4cc;
  text-align: right;
}

@media (max-width: 768px) {
  .message-list { padding: 16px 12px 8px; }
  .chat-input-area { padding: 10px 12px 14px; }
  .confirmation-wrapper, .escalation-inline { padding-left: 0; max-width: 100%; }
}
</style>
