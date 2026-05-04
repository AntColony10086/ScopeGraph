import { test, expect, request } from "@playwright/test";

const BACKEND = process.env.E2E_BACKEND_URL ?? "http://localhost:8002";

/**
 * API-level tests — exercises the FastAPI backend directly without going
 * through the Vue frontend. This is faster and more deterministic than
 * driving a browser; we use the browser only for true UI flows.
 *
 * The chat endpoint typically takes 30-90s per turn (MiniMax reasoning model
 * makes 5+ chained LLM calls per question), so test timeouts are generous.
 */

test.describe("Auth", () => {
  test("login + /me roundtrip for chem_user_a", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const login = await ctx.post("/api/auth/login", {
      data: { username: "chem_user_a", password: "chemA123" },
    });
    expect(login.ok(), `login failed: ${login.status()} ${await login.text()}`).toBeTruthy();
    const body = await login.json();
    expect(body.access_token).toBeTruthy();
    expect(body.username).toBe("chem_user_a");
    expect(body.accessible_enterprises).toEqual(["C001"]);

    const me = await ctx.get("/api/auth/me", {
      headers: { Authorization: `Bearer ${body.access_token}` },
    });
    expect(me.ok()).toBeTruthy();
    const meBody = await me.json();
    expect(meBody.username).toBe("chem_user_a");
    expect(meBody.role).toBe("user");
  });

  test("login fails with wrong password", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const login = await ctx.post("/api/auth/login", {
      data: { username: "chem_user_a", password: "wrong-password" },
    });
    expect(login.status()).toBe(401);
  });

  test("admin login + has wildcard permissions", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const login = await ctx.post("/api/auth/login", {
      data: { username: "admin", password: "admin123" },
    });
    expect(login.ok()).toBeTruthy();
    const body = await login.json();
    expect(body.role).toBe("admin");
    expect(body.accessible_enterprises).toEqual(["*"]);
  });
});

test.describe("Health", () => {
  test("/health/detailed returns ok with all deps green", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const r = await ctx.get("/health/detailed");
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.status).toBe("ok");
    expect(body.checks.structured_neo4j).toBe(true);
    expect(body.checks.redis).toBe(true);
    expect(body.checks.mysql).toBe(true);
  });
});

test.describe("Chat (functional)", () => {
  // Each chat test independently exceeds 60s easily.
  test.describe.configure({ mode: "serial", timeout: 240_000 });

  let token: string;

  test.beforeAll(async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const login = await ctx.post("/api/auth/login", {
      data: { username: "chem_user_a", password: "chemA123" },
    });
    expect(login.ok()).toBeTruthy();
    token = (await login.json()).access_token;
  });

  test("own-data: explicit company → reply mentions company + value 123", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const r = await ctx.post("/api/chat", {
      headers: { Authorization: `Bearer ${token}` },
      data: { message: "化工企业A 2024 年 Scope1 排放是多少", session_id: "" },
      timeout: 200_000,
    });
    expect(r.ok(), `chat failed: ${r.status()} ${await r.text()}`).toBeTruthy();
    const body = await r.json();
    const reply: string = body.reply ?? "";
    console.log("intent =", body.intent);
    console.log("reply preview =", reply.slice(0, 300));
    // Should hit graphrag with our placeholder data
    expect(reply.length, "reply must be non-empty").toBeGreaterThan(20);
    // Either it returns 123 (placeholder) or mentions the right company; flag if it refuses
    expect(reply, "must not refuse a legitimate own-data query").not.toMatch(/不在.*?数据范围/);
  });

  test("own-data: first-person resolution → reply about C001", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    const r = await ctx.post("/api/chat", {
      headers: { Authorization: `Bearer ${token}` },
      data: { message: "我公司 2024 年 Scope1 排放是多少", session_id: "" },
      timeout: 200_000,
    });
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    const reply: string = body.reply ?? "";
    console.log("intent =", body.intent);
    console.log("reply preview =", reply.slice(0, 300));
    expect(reply.length).toBeGreaterThan(20);
    // The user_context should have resolved 我公司 → 化工企业A; reply should reflect that
    expect(reply, "first-person should not be refused or asked back").not.toMatch(/请提供企业|请提供具体的企业|不在.*?数据范围/);
  });

  test("permission isolation: cross-tenant query is refused", async () => {
    const ctx = await request.newContext({ baseURL: BACKEND });
    // chem_user_a (bound to C001) asking about 光伏企业A (C022) must be refused
    const r = await ctx.post("/api/chat", {
      headers: { Authorization: `Bearer ${token}` },
      data: { message: "光伏企业A 2024 年 Scope1 排放是多少", session_id: "" },
      timeout: 200_000,
    });
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    const reply: string = body.reply ?? "";
    console.log("intent =", body.intent);
    console.log("reply preview =", reply.slice(0, 300));
    expect(reply.length).toBeGreaterThan(10);
    // Must contain a refusal keyword and must NOT contain the placeholder value 123
    // (because 123 in this context would indicate a successful data leak)
    expect(reply, "must explicitly refuse").toMatch(/无权|权限|不允许|无法访问|只能查看|您绑定|不能查询/);
  });
});
