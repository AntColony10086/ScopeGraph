<template>
  <el-card class="confirmation-card" shadow="hover">
    <template #header>
      <span class="confirmation-card__title">{{ title }}</span>
    </template>

    <p class="confirmation-card__body">{{ body }}</p>

    <el-button-group class="confirmation-card__actions">
      <el-button
        v-for="opt in options"
        :key="opt.value"
        type="primary"
        :loading="loading"
        :disabled="loading"
        @click="handleSelect(opt.value)"
      >
        {{ opt.label }}
      </el-button>
    </el-button-group>
  </el-card>
</template>

<script setup lang="ts">
import { ElButton, ElButtonGroup, ElCard } from "element-plus";

interface Option {
  label: string;
  value: string;
}

const props = defineProps<{
  title: string;
  body: string;
  options: Option[];
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: "select", value: string): void;
}>();

function handleSelect(value: string): void {
  if (props.loading) {
    return;
  }
  emit("select", value);
}
</script>

<style scoped>
.confirmation-card {
  max-width: 420px;
  margin: 12px 0;
}

.confirmation-card__title {
  font-weight: 600;
  font-size: 15px;
  color: #1f2937;
}

.confirmation-card__body {
  margin: 0 0 14px 0;
  font-size: 14px;
  line-height: 1.55;
  color: #4b5563;
  white-space: pre-wrap;
  word-break: break-word;
}

.confirmation-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
