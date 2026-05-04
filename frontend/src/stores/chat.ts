import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/utils/api'
import type { Message, ChatResponse } from '@/types'

export const useChatStore = defineStore('chat', () => {
  // --------------- state ---------------
  const messages = ref<Message[]>([])
  const sessionId = ref<string>('')
  const isLoading = ref(false)
  const currentEventSource = ref<EventSource | null>(null)
  const statusText = ref<string>('')  // Show current processing step
  const pendingImagePath = ref<string>('')
  const pendingFilePath = ref<string>('')

  // --------------- actions ---------------

  /** Start a brand-new chat session */
  function newSession(): void {
    messages.value = []
    sessionId.value = ''
    statusText.value = ''
    pendingImagePath.value = ''
    pendingFilePath.value = ''
    closeStream()
    messages.value.push({
      id: generateId(),
      role: 'assistant',
      content:
        '您好！欢迎使用「ScopeGraph: Multi-Agent Carbon Data Assistant」🏭\n\n我可以帮您查询：\n• 地区A 10 家主力化工企业的 Scope 1/2/3 排放、能源消耗、污染物排放\n• 配额履约缺口、CCER、绿证、节能技改投资\n• 历年趋势 + 企业对比 + 与内蒙/地区C/地区D/地区E/地区F的横向对标（数据范围 2019-2026）\n• MRV 口径、Scope 定义、CBAM 等合规知识\n\n试试问我："化工企业A 2023 年 Scope1 排放" 或 "化工企业D 2019 vs 2023 直接排放变化" 或 "地区A化工 2023 年配额履约缺口"',
      timestamp: new Date().toISOString(),
    })
  }

  /** Send a user message and receive AI response via SSE streaming */
  async function sendMessage(content: string): Promise<void> {
    if (!content.trim() || isLoading.value) return

    // Append user message
    messages.value.push({
      id: generateId(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString(),
    })

    // Create a placeholder for the assistant reply
    messages.value.push({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
    })
    const msgIndex = messages.value.length - 1
    isLoading.value = true
    statusText.value = ''

    const attachment = {
      image_path: pendingImagePath.value || undefined,
      file_path: pendingFilePath.value || undefined,
    }
    pendingImagePath.value = ''
    pendingFilePath.value = ''

    // Attachments currently go through POST so backend can receive image_path/file_path.
    if (attachment.image_path || attachment.file_path) {
      await fetchResponse(content, msgIndex, attachment)
      return
    }

    // Try SSE streaming first, fall back to POST
    try {
      await streamResponse(content, msgIndex)
    } catch {
      await fetchResponse(content, msgIndex)
    }
  }

  /** Stream the AI response via Server-Sent Events (true token-level) */
  async function streamResponse(
    content: string,
    msgIndex: number,
  ): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const token = localStorage.getItem('token') || ''
      if (!token) {
        reject(new Error('No token'))
        return
      }

      const params = new URLSearchParams({
        message: content,
        session_id: sessionId.value,
        token,
      })

      const url = `/api/chat/stream?${params.toString()}`
      const es = new EventSource(url)
      currentEventSource.value = es

      let hasContent = false

      es.onmessage = (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data)
          const eventType = payload.event

          switch (eventType) {
            case 'session':
              // Backend sends session_id
              if (payload.data) sessionId.value = payload.data
              break

            case 'thinking':
            case 'status':
              // Show processing status (not the final content)
              statusText.value = payload.data
              break

            case 'token':
              // Token-by-token streaming — clear status on first token
              if (!hasContent) {
                statusText.value = ''
                // Clear placeholder content
                messages.value[msgIndex] = {
                  ...messages.value[msgIndex],
                  content: '',
                }
                hasContent = true
              }
              // Append token to content
              messages.value[msgIndex] = {
                ...messages.value[msgIndex],
                content: messages.value[msgIndex].content + payload.data,
              }
              break

            case 'message':
              // Full message in one shot (fallback within SSE)
              statusText.value = ''
              hasContent = true
              messages.value[msgIndex] = {
                ...messages.value[msgIndex],
                content: payload.data,
              }
              break

            case 'done':
              statusText.value = ''
              messages.value[msgIndex] = {
                ...messages.value[msgIndex],
                isStreaming: false,
              }
              isLoading.value = false
              closeStream()
              resolve()
              break

            case 'error':
              statusText.value = ''
              messages.value[msgIndex] = {
                ...messages.value[msgIndex],
                content: messages.value[msgIndex].content + '\n[服务异常，请稍后重试]',
                isStreaming: false,
              }
              isLoading.value = false
              closeStream()
              resolve()
              break
          }
        } catch {
          // Non-JSON data, treat as token
          if (event.data) {
            messages.value[msgIndex] = {
              ...messages.value[msgIndex],
              content: messages.value[msgIndex].content + event.data,
            }
          }
        }
      }

      es.onerror = () => {
        closeStream()
        if (!hasContent) {
          // No content received at all — fall back to POST
          reject(new Error('SSE connection failed'))
        } else {
          // Partial content received, just finish up
          statusText.value = ''
          messages.value[msgIndex] = {
            ...messages.value[msgIndex],
            isStreaming: false,
          }
          isLoading.value = false
          resolve()
        }
      }
    })
  }

  /** Non-streaming fallback: plain POST /api/chat */
  async function fetchResponse(
    content: string,
    msgIndex: number,
    attachment?: {
      image_path?: string
      file_path?: string
    },
  ): Promise<void> {
    try {
      const { data } = await api.post<ChatResponse>('/chat', {
        message: content,
        session_id: sessionId.value,
        ...attachment,
      })

      if (data.session_id) sessionId.value = data.session_id

      messages.value[msgIndex] = {
        ...messages.value[msgIndex],
        content: data.reply || '收到回复但内容为空',
        isStreaming: false,
      }
    } catch {
      messages.value[msgIndex] = {
        ...messages.value[msgIndex],
        content: '抱歉，服务暂时不可用，请稍后重试。',
        isStreaming: false,
      }
    } finally {
      statusText.value = ''
      isLoading.value = false
    }
  }

  /** Confirm or cancel a Tier-2 operation */
  async function respondToConfirmation(
    operationId: string,
    action: 'confirm' | 'cancel',
  ): Promise<void> {
    try {
      await api.post('/chat/confirm', {
        operation_id: operationId,
        action,
        session_id: sessionId.value,
      })

      const msg = messages.value.find(
        (m) => m.confirmation?.operationId === operationId,
      )
      if (msg?.confirmation) {
        msg.confirmation.status = action === 'confirm' ? 'confirmed' : 'cancelled'
      }
    } catch {
      // silently fail
    }
  }

  function setPendingAttachment(payload: {
    imagePath?: string
    filePath?: string
  }): void {
    pendingImagePath.value = payload.imagePath || ''
    pendingFilePath.value = payload.filePath || ''
  }

  /** Close the active SSE connection */
  function closeStream(): void {
    if (currentEventSource.value) {
      currentEventSource.value.close()
      currentEventSource.value = null
    }
  }

  /** Generate a random local ID */
  function generateId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
  }

  return {
    messages,
    sessionId,
    isLoading,
    statusText,
    newSession,
    sendMessage,
    respondToConfirmation,
    setPendingAttachment,
    closeStream,
  }
})
