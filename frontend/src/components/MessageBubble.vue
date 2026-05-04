<template>
  <div
    class="bubble-row"
    :class="{ 'bubble-row--user': isUser, 'bubble-row--assistant': !isUser }"
  >
    <div class="bubble" :class="bubbleClass">
      <div class="bubble__content">{{ cleanedContent }}</div>
      <div v-if="status" class="bubble__status">{{ status }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  role: "user" | "assistant" | "system";
  content: string;
  status?: string;
}>();

const isUser = computed(() => props.role === "user");

const bubbleClass = computed(() => ({
  "bubble--user": isUser.value,
  "bubble--assistant": props.role === "assistant",
  "bubble--system": props.role === "system",
}));

/**
 * Strip ``<think>...</think>`` reasoning blocks so end users only see
 * the polished answer. The check is assistant-side only — a user
 * literally typing those tags is left alone.
 */
const cleanedContent = computed(() => {
  if (props.role !== "assistant") {
    return props.content;
  }
  return props.content.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
});
</script>

<style scoped>
.bubble-row {
  display: flex;
  margin: 8px 0;
  width: 100%;
}

.bubble-row--user {
  justify-content: flex-end;
}

.bubble-row--assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.55;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.bubble__content {
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble__status {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.7;
  font-style: italic;
}

.bubble--user {
  background: linear-gradient(135deg, #4f8cff 0%, #2563eb 100%);
  color: #ffffff;
  border-top-right-radius: 4px;
}

.bubble--assistant {
  background-color: #f3f4f6;
  color: #1f2937;
  border-top-left-radius: 4px;
}

.bubble--system {
  background-color: #fef3c7;
  color: #78350f;
  font-size: 13px;
  font-style: italic;
}
</style>
