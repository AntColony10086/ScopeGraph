<template>
  <div class="login-page">
    <div class="bg" aria-hidden="true"></div>

    <main class="shell">
      <section class="grid">
        <!-- ==================== Left: brand + visual + facts ==================== -->
        <aside class="left">
          <header class="brand">
            <div class="brand__row">
              <div class="brand__mark" aria-hidden="true">
                <svg viewBox="0 0 32 32" width="22" height="22">
                  <path
                    d="M16 4 L25 9 L25 19 C25 23 21 27 16 28 C11 27 7 23 7 19 L7 9 Z"
                    fill="none"
                    stroke="rgba(255,255,255,0.95)"
                    stroke-width="1.6"
                    stroke-linejoin="round"
                  />
                  <path
                    d="M11.5 16.5 L14.5 19.5 L20.5 12.5"
                    fill="none"
                    stroke="rgba(255,255,255,0.95)"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>
              <div class="brand__text">
                <h1 class="brand__title">
                  ScopeGraph
                  <span class="brand__en">ScopeGraph</span>
                </h1>
                <p class="brand__sub">
                  地区A · 化工 / 石油化工 / 光伏 / 煤炭 — 碳排放与能耗数据库
                </p>
              </div>
            </div>
          </header>

          <div class="visual">
            <svg
              class="scene"
              viewBox="0 0 900 680"
              role="img"
              aria-label="碳数据与地区A工业地形可视化背景"
              preserveAspectRatio="xMidYMid slice"
            >
              <defs>
                <linearGradient id="gSky" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stop-color="#0d9488" stop-opacity="0.22" />
                  <stop offset="0.55" stop-color="#064e3b" stop-opacity="0.18" />
                  <stop offset="1" stop-color="#052f24" stop-opacity="0.12" />
                </linearGradient>
                <linearGradient id="gLine" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stop-color="#7de3d8" stop-opacity="0.18" />
                  <stop offset="0.5" stop-color="#7de3d8" stop-opacity="0.55" />
                  <stop offset="1" stop-color="#7de3d8" stop-opacity="0.14" />
                </linearGradient>
                <linearGradient id="gMountain" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#dff7f3" stop-opacity="0.12" />
                  <stop offset="1" stop-color="#dff7f3" stop-opacity="0.04" />
                </linearGradient>
                <radialGradient id="gGlow" cx="50%" cy="45%" r="65%">
                  <stop offset="0" stop-color="#8ef0e5" stop-opacity="0.22" />
                  <stop offset="1" stop-color="#8ef0e5" stop-opacity="0" />
                </radialGradient>
              </defs>

              <rect x="0" y="0" width="900" height="680" fill="url(#gSky)" />
              <circle cx="450" cy="320" r="260" fill="url(#gGlow)" />

              <!-- 山脊（西部地形） -->
              <g class="float-slow" opacity="0.95">
                <path
                  d="M0 465 L120 410 L220 440 L310 390 L420 448 L520 360 L640 435 L745 395 L900 455 L900 680 L0 680 Z"
                  fill="url(#gMountain)"
                />
                <path
                  d="M0 520 L130 470 L235 505 L340 455 L455 520 L560 430 L690 510 L795 468 L900 525"
                  fill="none"
                  stroke="#b9efe6"
                  stroke-opacity="0.22"
                  stroke-width="2"
                />
              </g>

              <!-- 工业装置剪影 -->
              <g class="float-fast" opacity="0.9">
                <g transform="translate(84, 360)">
                  <rect x="0" y="160" width="250" height="120" rx="12" fill="#dff7f3" fill-opacity="0.07" />
                  <rect x="24" y="128" width="62" height="152" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                  <rect x="100" y="96" width="44" height="184" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                  <rect x="160" y="120" width="50" height="160" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                  <path
                    d="M22 168 C18 150, 40 140, 48 154 C54 164, 44 172, 38 174 C32 176, 26 174, 22 168 Z"
                    fill="#8ef0e5"
                    fill-opacity="0.18"
                  />
                  <path
                    d="M110 132 C102 110, 132 100, 142 118 C150 132, 134 142, 126 144 C118 146, 112 142, 110 132 Z"
                    fill="#8ef0e5"
                    fill-opacity="0.18"
                  />
                </g>

                <g transform="translate(610, 350)">
                  <rect x="0" y="190" width="220" height="90" rx="12" fill="#dff7f3" fill-opacity="0.06" />
                  <rect x="22" y="120" width="54" height="160" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                  <rect x="92" y="90" width="44" height="190" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                  <rect x="152" y="138" width="52" height="142" rx="10" fill="#dff7f3" fill-opacity="0.08" />
                </g>
              </g>

              <!-- 碳数据网络 -->
              <g class="float-slow" opacity="0.92">
                <path
                  d="M170 250 C260 220, 340 240, 420 205 C510 165, 610 170, 720 210"
                  fill="none"
                  stroke="url(#gLine)"
                  stroke-width="3"
                />
                <path
                  d="M210 320 C300 295, 360 315, 450 290 C560 258, 650 270, 748 305"
                  fill="none"
                  stroke="url(#gLine)"
                  stroke-width="2.5"
                  stroke-opacity="0.7"
                />
                <path
                  d="M260 185 C330 150, 380 155, 460 130 C560 95, 650 112, 720 150"
                  fill="none"
                  stroke="url(#gLine)"
                  stroke-width="2"
                  stroke-opacity="0.55"
                />
                <g>
                  <circle cx="170" cy="250" r="8" fill="#8ef0e5" fill-opacity="0.55" />
                  <circle cx="420" cy="205" r="9" fill="#8ef0e5" fill-opacity="0.62" />
                  <circle cx="720" cy="210" r="8" fill="#8ef0e5" fill-opacity="0.55" />
                  <circle cx="210" cy="320" r="7" fill="#bff7ef" fill-opacity="0.5" />
                  <circle cx="450" cy="290" r="8" fill="#bff7ef" fill-opacity="0.58" />
                  <circle cx="748" cy="305" r="7" fill="#bff7ef" fill-opacity="0.5" />
                  <circle cx="260" cy="185" r="6.5" fill="#d8fbf7" fill-opacity="0.42" />
                  <circle cx="460" cy="130" r="7.2" fill="#d8fbf7" fill-opacity="0.5" />
                  <circle cx="720" cy="150" r="6.5" fill="#d8fbf7" fill-opacity="0.42" />
                </g>
                <g transform="translate(458, 132)" opacity="0.9">
                  <circle cx="0" cy="0" r="26" fill="none" stroke="#8ef0e5" stroke-opacity="0.22" stroke-width="2" />
                  <circle cx="0" cy="0" r="12" fill="none" stroke="#8ef0e5" stroke-opacity="0.35" stroke-width="2" />
                  <path
                    d="M-30 0 A30 30 0 0 1 30 0"
                    fill="none"
                    stroke="#8ef0e5"
                    stroke-opacity="0.18"
                    stroke-width="2.5"
                  />
                </g>
              </g>

              <rect x="0" y="520" width="900" height="160" fill="#052f24" fill-opacity="0.08" />
            </svg>

            <div class="facts">
              <div class="facts__title">平台概览</div>
              <ul class="facts__list">
                <li class="facts__item">
                  <span class="facts__k">覆盖企业</span>
                  <span class="facts__v">13 家 · 4 大行业</span>
                </li>
                <li class="facts__item">
                  <span class="facts__k">数据范围</span>
                  <span class="facts__v">2019 – 2026</span>
                </li>
                <li class="facts__item">
                  <span class="facts__k">核心能力</span>
                  <span class="facts__v">碳排放 · 能耗 · 履约</span>
                </li>
              </ul>
            </div>
          </div>

          <footer class="left-foot">
            合规口径可追溯 · 指标体系统一 · 面向企业 ESG 与碳合规岗位
          </footer>
        </aside>

        <!-- ==================== Right: form ==================== -->
        <section class="right">
          <div class="card">
            <div class="card__head">
              <div class="card__title">登录工作台</div>
              <div class="card__desc">使用账号密码进入「ScopeGraph」企业碳数据平台</div>
            </div>

            <el-form
              ref="formRef"
              class="form"
              :model="form"
              :rules="rules"
              label-position="top"
              @submit.prevent="onSubmit"
            >
              <el-form-item prop="username" label="账号">
                <el-input
                  v-model="form.username"
                  size="large"
                  placeholder="请输入账号"
                  autocomplete="username"
                  clearable
                  :prefix-icon="User"
                />
              </el-form-item>

              <el-form-item prop="password" label="密码">
                <el-input
                  v-model="form.password"
                  size="large"
                  type="password"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                  show-password
                  :prefix-icon="Lock"
                  @keyup.enter="onSubmit"
                />
              </el-form-item>

              <el-button
                class="login-btn"
                type="primary"
                size="large"
                :loading="authStore.loading"
                @click="onSubmit"
              >
                登 录
              </el-button>
            </el-form>

            <div class="accounts">
              <div class="accounts__title">体验账号（任选一个，密码 = 用户名 + 123）</div>
              <div class="accounts__grid">
                <button
                  v-for="acc in DEMO_ACCOUNTS"
                  :key="acc.username"
                  type="button"
                  class="account-pill"
                  @click="useAccount(acc)"
                >
                  <span class="pill__role" :data-role="acc.role">{{ acc.label }}</span>
                  <span class="pill__name">{{ acc.username }}</span>
                </button>
              </div>
            </div>
          </div>

          <p class="copyright">
            ScopeGraph 范畴图谱 &copy; {{ currentYear }} · v1.0
          </p>
        </section>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'

interface DemoAccount {
  label: string
  username: string
  password: string
  role: 'admin' | 'chemical' | 'petchem' | 'solar' | 'coal'
}

const DEMO_ACCOUNTS: DemoAccount[] = [
  { label: '管理员', username: 'admin', password: 'admin123', role: 'admin' },
  { label: '化工', username: 'chem_user_a', password: 'test123', role: 'chemical' },
  { label: '石化', username: 'petchem_user_a', password: 'petchem123', role: 'petchem' },
  { label: '光伏', username: 'solar_user_a', password: 'solar123', role: 'solar' },
  { label: '煤炭', username: 'coal_user_a', password: 'coal123', role: 'coal' },
]

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 4, message: '密码长度不能少于 4 位', trigger: 'blur' },
  ],
}

const currentYear = computed(() => new Date().getFullYear())

function useAccount(acc: DemoAccount) {
  form.username = acc.username
  form.password = acc.password
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  try {
    await authStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (err: unknown) {
    const msg =
      (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      '登录失败，请检查账号或密码'
    ElMessage.error(msg)
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  position: relative;
  color: rgba(255, 255, 255, 0.92);
  overflow: hidden;
}

/* ──────────── Background ──────────── */
.bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(1200px 800px at 20% 20%, rgba(13, 148, 136, 0.35), transparent 55%),
    radial-gradient(900px 700px at 80% 25%, rgba(6, 78, 59, 0.35), transparent 55%),
    radial-gradient(900px 700px at 55% 85%, rgba(9, 92, 80, 0.22), transparent 55%),
    linear-gradient(135deg, #063f35 0%, #052f24 45%, #041f18 100%);
}

.bg::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
  background-size: 44px 44px;
  opacity: 0.12;
  -webkit-mask-image: radial-gradient(600px 450px at 30% 35%, #000 40%, transparent 70%);
  mask-image: radial-gradient(600px 450px at 30% 35%, #000 40%, transparent 70%);
  pointer-events: none;
}

/* ──────────── Layout ──────────── */
.shell {
  position: relative;
  z-index: 1;
  min-height: 100vh;
  display: flex;
  align-items: stretch;
  justify-content: center;
  padding: 28px 18px;
}

.grid {
  width: min(1160px, 100%);
  display: grid;
  grid-template-columns: 1.25fr 0.9fr;
  gap: 22px;
  align-items: stretch;
}

.left {
  border-radius: 22px;
  padding: 22px 22px 18px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow:
    0 24px 80px rgba(0, 0, 0, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  display: flex;
  flex-direction: column;
  animation: enter 520ms ease both;
}

.right {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
  animation: enter 520ms ease both 60ms;
}

/* ──────────── Brand ──────────── */
.brand__row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.brand__mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background:
    radial-gradient(14px 14px at 30% 30%, rgba(255, 255, 255, 0.36), transparent 60%),
    linear-gradient(135deg, rgba(13, 148, 136, 0.95), rgba(6, 78, 59, 0.92));
  box-shadow:
    0 10px 26px rgba(0, 0, 0, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand__title {
  margin: 0;
  font-size: 22px;
  font-weight: 720;
  letter-spacing: 0.2px;
  line-height: 1.15;
}

.brand__en {
  margin-left: 10px;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.78;
  letter-spacing: 0.6px;
}

.brand__sub {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
  opacity: 0.82;
  max-width: 640px;
}

/* ──────────── Visual ──────────── */
.visual {
  margin-top: 14px;
  position: relative;
  flex: 1;
  display: grid;
  grid-template-rows: 1fr auto;
  gap: 14px;
  min-height: 380px;
}

.scene {
  width: 100%;
  height: 100%;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.10);
  background: rgba(255, 255, 255, 0.03);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 18px 60px rgba(0, 0, 0, 0.28);
  overflow: hidden;
}

.facts {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.10);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.facts__title {
  font-size: 13px;
  font-weight: 700;
  opacity: 0.88;
  letter-spacing: 0.4px;
}

.facts__list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 9px;
}

.facts__item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.facts__k {
  font-size: 12px;
  opacity: 0.78;
}

.facts__v {
  font-size: 13px;
  font-weight: 650;
  opacity: 0.92;
}

.left-foot {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.10);
  font-size: 12px;
  opacity: 0.72;
  line-height: 1.6;
}

/* ──────────── Form card ──────────── */
.card {
  border-radius: 22px;
  padding: 24px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow:
    0 24px 80px rgba(0, 0, 0, 0.38),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: rgba(3, 31, 24, 0.92);
}

.card__head { margin-bottom: 14px; }

.card__title {
  font-size: 18px;
  font-weight: 780;
  letter-spacing: 0.2px;
}

.card__desc {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(3, 31, 24, 0.64);
  line-height: 1.5;
}

.form { margin-top: 10px; }

.login-btn {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border-radius: 14px;
  border: 0;
  font-size: 15px;
  letter-spacing: 4px;
  background: linear-gradient(135deg, #0d9488 0%, #0b7f74 40%, #064e3b 100%);
  box-shadow:
    0 12px 28px rgba(6, 78, 59, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.18);
  transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
}

.login-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.05);
  box-shadow:
    0 16px 34px rgba(6, 78, 59, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.login-btn:active {
  transform: translateY(0);
  filter: brightness(0.98);
}

/* ──────────── Demo accounts ──────────── */
.accounts {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed rgba(6, 78, 59, 0.18);
}

.accounts__title {
  font-size: 12px;
  color: rgba(3, 31, 24, 0.62);
  margin-bottom: 8px;
}

.accounts__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.account-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(6, 78, 59, 0.18);
  background: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  font-size: 12px;
  color: rgba(3, 31, 24, 0.78);
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.12s ease;
}

.account-pill:hover {
  background: rgba(13, 148, 136, 0.08);
  border-color: rgba(13, 148, 136, 0.45);
  transform: translateY(-1px);
}

.pill__role {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(13, 148, 136, 0.14);
  color: #0d9488;
}

.pill__role[data-role="admin"] {
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}

.pill__name {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 11.5px;
}

.copyright {
  margin: 0;
  text-align: center;
  font-size: 12px;
  opacity: 0.6;
}

/* ──────────── Element Plus overrides ──────────── */
:deep(.el-form-item__label) {
  color: rgba(3, 31, 24, 0.72) !important;
  font-weight: 650;
  padding-bottom: 4px !important;
}

:deep(.el-input__wrapper) {
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: none !important;
  border: 1px solid rgba(6, 78, 59, 0.14);
  padding: 0 12px;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

:deep(.el-input__wrapper.is-focus) {
  border-color: rgba(13, 148, 136, 0.55);
  box-shadow: 0 0 0 4px rgba(13, 148, 136, 0.14) !important;
  background: rgba(255, 255, 255, 0.92);
}

:deep(.el-input__inner) {
  height: 44px !important;
  font-size: 14px;
  color: rgba(3, 31, 24, 0.92);
}

:deep(.el-input__prefix-inner) {
  color: rgba(6, 78, 59, 0.58);
  font-size: 16px;
}

/* ──────────── SVG motion ──────────── */
.float-slow {
  transform-origin: 50% 50%;
  animation: floatY 10.5s ease-in-out infinite;
}
.float-fast {
  transform-origin: 50% 50%;
  animation: floatY 8.2s ease-in-out infinite;
}

@keyframes floatY {
  0%   { transform: translateY(0); }
  50%  { transform: translateY(-6px); }
  100% { transform: translateY(0); }
}

@keyframes enter {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ──────────── Responsive ──────────── */
@media (max-width: 1024px) {
  .grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }
  .left { padding: 18px 16px 14px; }
  .right { justify-content: flex-start; }
  .visual { min-height: 320px; }
}

@media (max-width: 480px) {
  .shell { padding: 16px 12px; }
  .card { padding: 20px 18px; }
  .brand__title { font-size: 19px; }
  .brand__en { display: block; margin: 4px 0 0; }
}

/* Respect reduced-motion preference */
@media (prefers-reduced-motion: reduce) {
  .float-slow,
  .float-fast,
  .left,
  .right {
    animation: none !important;
  }
}
</style>
