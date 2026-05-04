# API Reference

本文档列出 ScopeGraph 后端的全部 REST 与 SSE 接口。
所有 JSON 请求体使用 `Content-Type: application/json`，所有受保护接口
均需在头部携带 `Authorization: Bearer <jwt>`。

> 默认 `BASE=http://localhost:8001`，前端开发时由 Vite 反代到该端口。

---

## 1. 认证 / Auth

### 1.1 `POST /api/auth/login`

用户登录，返回 JWT。

**请求**

```json
{
  "username": "admin",
  "password": "<plaintext>"
}
```

**响应 (200)**

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "user_id": 1,
    "username": "admin",
    "role": "admin",
    "enterprise_id": null
  }
}
```

**curl**

```bash
curl -sX POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"change-me"}'
```

### 1.2 `POST /api/auth/register`

注册新账号（默认仅管理员可调用，受 RBAC 保护）。

**请求**

```json
{
  "username": "tenant_a",
  "password": "<plaintext>",
  "role": "tenant",
  "enterprise_id": "C001"
}
```

字段约束：
- `role` ∈ `{admin, tenant}`
- `enterprise_id`：当 `role == "tenant"` 时必填，对应 `Customer.CustomerID`

**响应 (201)**：与 `/login` 相同结构。

### 1.3 `POST /api/auth/refresh`

旧 token 未过期且即将过期时刷新。

**请求**：仅头部 `Authorization: Bearer <old_token>`，请求体为空。

**响应**：与 `/login` 相同结构。

### 1.4 `GET /api/auth/me`

返回当前 token 解码后的用户信息。

**响应 (200)**

```json
{
  "user_id": 1,
  "username": "admin",
  "role": "admin",
  "enterprise_id": null,
  "issued_at": 1714780800,
  "expires_at": 1714867200
}
```

---

## 2. 对话 / Chat

### 2.1 `POST /api/chat`

同步对话（一次性返回完整答案）。

**请求**

```json
{
  "message": "化工企业A 2024 年 Scope1 排放是多少？",
  "session_id": "<可选；不传则后端生成>",
  "context": {
    "language": "zh-CN"
  }
}
```

**响应 (200)**

```json
{
  "session_id": "sess_abc123",
  "answer": "化工企业A 2024 年厂区 Scope1 CO2 排放总量为 123 万吨 CO2/年（数据来源：行业协会 A）。",
  "warnings": [],
  "evidence": [
    {
      "enterprise": "化工企业A",
      "year": 2024,
      "indicator": "厂区Scope1 CO2排放总量",
      "value": 123,
      "unit": "万吨CO2/年"
    }
  ],
  "intent": "graphrag",
  "elapsed_ms": 1234
}
```

`warnings` 字段非空时表示 hallucination_check 节点判定答案中有未被检索证据支撑的论断，
前端会在气泡上方显示警示横幅。

### 2.2 `GET /api/chat/stream`

SSE 流式对话。前端使用 `EventSource` 订阅。

**请求**：query 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `message` | 是 | URL-encoded 用户输入 |
| `session_id` | 否 | 不传则后端生成 |
| `token` | 是 | URL-encoded JWT（EventSource 不支持自定义 header，因此走 query） |

**事件类型**

| event | data 内容 | 频率 | 说明 |
|-------|-----------|------|------|
| `session` | `{"session_id":"sess_abc123"}` | 1 次 | 会话绑定 |
| `thinking` | `{"text":"...planner output..."}` | 0–N 次 | planner / 路由的中间推理（前端默认折叠） |
| `status` | `{"stage":"retrieve","detail":"querying neo4j"}` | 0–N 次 | 检索阶段进度 |
| `token` | `{"text":"化"}` | 多次 | 最终答案 token 流 |
| `message` | 与 `POST /api/chat` 响应一致 | 1 次 | 完整答案对象 |
| `error` | `{"code":"...","message":"..."}` | 0–1 次 | 任意阶段失败 |
| `done` | `{}` | 1 次 | 流结束 |

**curl**

```bash
curl -N "$BASE/api/chat/stream?token=$JWT&message=$(python -c 'import urllib.parse;print(urllib.parse.quote("Scope1 是什么"))')"
```

### 2.3 `POST /api/chat/upload`

文件上传（PDF / DOCX / XLSX / PNG / JPG），最大 10 MB。
上传成功后返回 `file_id`，下次 `/api/chat` 调用可在 `context.attachments` 中引用。

**请求**：`multipart/form-data`

```
file=@/path/to/report.pdf
session_id=sess_abc123
```

**响应 (200)**

```json
{
  "file_id": "file_xyz789",
  "filename": "report.pdf",
  "mime": "application/pdf",
  "size_bytes": 234567,
  "summary": "本文件为某企业 2024 年环保信息披露报告..."
}
```

`summary` 由 `file_query` 节点抽取生成（PDF 走 pdfplumber，DOCX 走 python-docx，
XLSX 走 openpyxl）。

### 2.4 `POST /api/chat/confirm`

二级确认。当 `additional_info` 子图判定用户输入存在歧义（"化工企业 A？还是 A 公司？"）
时，会先返回一个候选列表；前端展示后用户点选，再调用此接口确认。

**请求**

```json
{
  "session_id": "sess_abc123",
  "confirmation_id": "conf_001",
  "selected_index": 0
}
```

**响应**：与 `POST /api/chat` 一致。

---

## 3. 用户 / Profile

### 3.1 `GET /api/profile`

```json
{
  "user_id": 1,
  "username": "admin",
  "display_name": "管理员",
  "avatar_url": null,
  "preferences": {
    "default_language": "zh-CN",
    "default_year": 2024
  }
}
```

### 3.2 `PUT /api/profile`

```json
{
  "display_name": "新昵称",
  "preferences": {"default_language":"en"}
}
```

### 3.3 `POST /api/profile/avatar`

`multipart/form-data` 上传头像，限 PNG / JPG ≤ 2 MB。返回 `{ "avatar_url": "/static/avatars/..." }`。

---

## 4. 数据 / Data

> 所有 `data` 接口受 RBAC 保护：管理员可对全部企业读写；
> tenant 角色仅能读写自身 `enterprise_id` 绑定的企业数据。

### 4.1 `GET /api/data/observations`

**query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `enterprise_id` | string | 可选；不传 = 当前用户绑定的企业 |
| `year_from` / `year_to` | int | 年份区间 |
| `category` | string | 大类筛选，如 `Scope1` |
| `limit` | int | 默认 100，最大 500 |

**响应 (200)**

```json
{
  "items": [
    {
      "id": 1,
      "enterprise": "化工企业A",
      "year": 2024,
      "indicator": "厂区Scope1 CO2排放总量",
      "category": "Scope1",
      "value": 123,
      "unit": "万吨CO2/年",
      "source": "行业协会 A"
    }
  ],
  "total": 1
}
```

### 4.2 `POST /api/data/observations`

新增 / 更新一条观测（按 `(enterprise_id, year, product_id)` 幂等）。

**请求**

```json
{
  "enterprise_id": "C001",
  "year": 2024,
  "product_id": 1,
  "value": 123,
  "shipper_id": 1,
  "employee_id": 1
}
```

**响应 (201)**

```json
{ "id": 42, "operation": "created" }
```

### 4.3 `DELETE /api/data/observations/{id}`

按主键删除。返回 `204 No Content`；越权返回 `403`。

---

## 5. 健康检查 / Health

### 5.1 `GET /health/`

简单存活探针，仅返回 `{"status":"ok"}`，不检查依赖。

### 5.2 `GET /health/detailed`

逐依赖健康检查。

```json
{
  "status": "ok",
  "checks": {
    "redis": "ok",
    "neo4j_structured": "ok",
    "neo4j_unstructured": "ok",
    "mysql": "ok",
    "llm": "ok"
  },
  "version": "0.1.0",
  "uptime_seconds": 3600
}
```

任意依赖不可用时整体返回 `503`，`status` 字段置 `degraded`。

---

## 6. 错误码

所有错误响应统一形如：

```json
{
  "error": {
    "code": "AUTH_INVALID_TOKEN",
    "message": "JWT signature verification failed"
  }
}
```

| HTTP | code | 含义 |
|------|------|------|
| 400 | `BAD_REQUEST` | 入参 schema 校验失败 |
| 401 | `AUTH_INVALID_TOKEN` / `AUTH_EXPIRED` | 凭证无效 / 过期 |
| 403 | `RBAC_DENIED` | 角色 / 租户不允许 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 重复主键 / 并发冲突 |
| 413 | `PAYLOAD_TOO_LARGE` | 上传超 10 MB |
| 422 | `VALIDATION_ERROR` | Pydantic 校验失败（带 `details`） |
| 429 | `RATE_LIMITED` | 限流命中 |
| 500 | `INTERNAL` | 未捕获异常 |
| 503 | `DEPENDENCY_UNAVAILABLE` | Redis / Neo4j / MySQL / LLM 依赖故障 |
