// Current-conversation QQ interactions; no arbitrary OneBot action or destination.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const INTERACTIONS_ROUTE = '/api/socialV2/atri-interactions';
const flags = { find_faces: 'findFaces', send_face: 'sendFace', reaction: 'setMessageReaction' };
function fail(message, status = 400) { throw Object.assign(new Error(message), { status }); }
function integer(value, signed = false) {
  const s = String(value ?? '');
  if (!(signed ? /^-?[1-9]\d{0,15}$/ : /^(0|[1-9]\d{0,6})$/).test(s) || !Number.isSafeInteger(Number(s))) fail('表情或消息编号无效');
  return s;
}
function emojiId(value) {
  const s = String(value ?? '').replace(/\uFE0F/g, '');
  if (/^\d+$/.test(s)) {
    const n = Number(integer(s));
    if (n > 0x10ffff || (n >= 0xd800 && n <= 0xdfff)) fail('emoji 编号无效');
    return String(n);
  }
  if ([...s].length !== 1 || !/\p{Extended_Pictographic}/u.test(s)) fail('请使用单个 emoji（如 👍、❤️）或真实 QQ 表情编号，不支持组合 emoji');
  return String(s.codePointAt(0));
}
function faceView(face) {
  return { id: String(face.q_sid ?? ''), name: String(face.q_des ?? '').slice(0, 80),
    aliases: (Array.isArray(face.emoji_name_alias) ? face.emoji_name_alias : []).slice(0, 8).map(v => String(v).slice(0, 80)),
    sendable: /^(0|[1-9]\d{0,6})$/.test(String(face.q_sid ?? '')) };
}

export function createInteractions({ getConfig, getMode, authorize, getExpectedAccount,
  action, captureGuard, reserve, record, ledgerPath, now = Date.now }) {
  let busy = false;
  function authority(input, token) {
    const cfg = getConfig();
    const match = /^(private|group):([1-9]\d{0,15})$/.exec(String(input.key ?? ''));
    if (!match || !Number.isSafeInteger(Number(match[2]))) fail('会话 key 无效');
    if (!Object.hasOwn(flags, input.operation)) fail('不支持的 QQ 互动操作');
    if (getMode() !== 'reserved2' || cfg.socialV2?.enabled === false || !token || !authorize(input.key, token)) fail('当前聊天的二代会话令牌或权限无效', 403);
    const list = match[1] === 'group' ? 'groups' : 'private';
    const allow = (cfg.allow?.[list] ?? []).map(String);
    if ((cfg.deny?.[list] ?? []).map(String).includes(match[2]) || !(allow.length ? allow.includes(match[2]) : cfg.allowAllWhenEmpty === true)) fail('当前聊天不在允许范围内', 403);
    if (cfg.socialV2?.tools?.[flags[input.operation]] === false) fail('该 QQ 互动工具已关闭', 403);
    return { kind: match[1], id: Number(match[2]) };
  }
  function readLedger() {
    try {
      const data = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
      if (!data || Array.isArray(data) || typeof data !== 'object' || Object.values(data).some(v =>
        !v || !['pending', 'sent', 'unknown'].includes(v.status) || !Number.isFinite(v.time) || typeof v.hash !== 'string')) throw Error();
      return data;
    } catch (e) { if (e.code === 'ENOENT') return {}; fail('互动记录不可读，停止写操作', 503); }
  }
  function saveLedger(data) {
    try {
      fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
      const tmp = `${ledgerPath}.${process.pid}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(data), { mode: 0o600, flush: true });
      fs.renameSync(tmp, ledgerPath);
    } catch { fail('互动记录保存失败，请核实发送结果，禁止自动重试', 503); }
  }
  async function execute(input, token) {
    const destination = authority(input, token);
    const write = input.operation !== 'find_faces';
    if (busy && write) fail('已有互动进行中，请先等待结果', 409);
    if (write) busy = true;
    try {
      const guard = write ? captureGuard(input.key) : () => {};
      const expected = String(getExpectedAccount());
      if (!/^[1-9]\d{0,15}$/.test(expected)) fail('桌面账号绑定无效', 403);
      let method, params, label;
      if (input.operation === 'find_faces') {
        if (typeof input.query !== 'string' || !input.query.trim() || input.query.length > 80) fail('表情搜索词需为 1–80 个字符');
      } else if (input.operation === 'send_face') {
        const faceId = integer(input.faceId);
        const face = await action('fetch_face_entity', { face_id: Number(faceId), refresh: false });
        if (!face || String(face.q_sid) !== faceId) fail('QQ 表情编号不存在，请先搜索目录');
        method = destination.kind === 'group' ? 'send_group_msg' : 'send_private_msg';
        params = { [destination.kind === 'group' ? 'group_id' : 'user_id']: destination.id,
          message: [{ type: 'face', data: { id: faceId } }] };
        label = `[QQ表情] ${String(face.q_des ?? faceId).slice(0, 80)}`;
      } else {
        // Installed SnowLuma supports message reactions only in groups.
        if (destination.kind !== 'group') fail('当前 SnowLuma 仅支持群消息表情回应');
        const messageId = Number(integer(input.messageId, true));
        const emoji = emojiId(input.emoji);
        if (input.set !== undefined && typeof input.set !== 'boolean') fail('set 必须为布尔值');
        const message = await action('get_msg', { message_id: messageId });
        if (message?.message_type !== 'group' || String(message.group_id) !== String(destination.id) || String(message.message_id) !== String(messageId)) fail('该消息无法确认为当前群消息', 403);
        method = 'set_msg_emoji_like';
        params = { message_id: messageId, emoji_id: emoji, set: input.set ?? true };
        label = `[消息表情回应] ${params.set ? '添加' : '取消'} ${emoji} → ${messageId}`;
      }
      const login = await action('get_login_info', {});
      if (String(login?.user_id) !== expected || String(getExpectedAccount()) !== expected) fail('SnowLuma 当前账号与桌面绑定不符', 403);
      authority(input, token);
      guard();
      if (!write) {
        const result = await action('search_sys_faces', { query: input.query });
        authority(input, token);
        return { faces: (Array.isArray(result?.faces) ? result.faces : []).slice(0, 30).filter(Boolean).map(faceView) };
      }
      if (typeof input.requestId !== 'string' || !/^[A-Za-z0-9_-]{8,80}$/.test(input.requestId)) fail('写操作需固定 requestId（8–80 位字母、数字、下划线或短横线）');
      const ledger = readLedger();
      const key = crypto.createHash('sha256').update(`${expected}:${input.key}:${input.requestId}`).digest('hex');
      const hash = crypto.createHash('sha256').update(JSON.stringify({ method, params })).digest('hex');
      if (ledger[key]) {
        if (ledger[key].hash !== hash) fail('同一 requestId 不可用于不同互动', 409);
        return { status: ledger[key].status === 'sent' ? 'already_sent' : 'unknown', requestId: input.requestId };
      }
      for (const [k, v] of Object.entries(ledger)) if (v.status === 'sent' && now() - v.time > 7 * 86400000) delete ledger[k];
      if (Object.keys(ledger).length >= 5000) fail('互动记录已满，请核查未知请求', 503);
      // Reserve from the bridge's shared send budget; no async gap before dispatch.
      authority(input, token);
      guard();
      reserve(input.key);
      ledger[key] = { hash, time: now(), status: 'pending' };
      saveLedger(ledger);
      let result;
      try { result = await action(method, params); }
      catch { ledger[key].status = 'unknown'; saveLedger(ledger); fail('QQ 互动结果待核实，禁止自动换请求 ID 重试', 502); }
      ledger[key].status = 'sent';
      saveLedger(ledger);
      record(input.key, label);
      return { status: 'sent', requestId: input.requestId, ...(result?.message_id !== undefined ? { message_id: result.message_id } : {}) };
    } finally { if (write) busy = false; }
  }
  return async (input, token) => {
    try { return { status: 200, body: { ok: true, data: await execute(input, token) } }; }
    catch (e) { return { status: e.status ?? 503, body: { ok: false, error: e.status ? e.message : 'QQ 互动暂不可用，请检查本地账号、服务及权限；写操作请先核实结果' } }; }
  };
}

export function registerInteractionTools(server, z, agentApi, serialize, tools = {}) {
  const base = { key: z.string().describe('当前聊天 key，必须使用当前会话令牌，不能填其他聊天'), token: z.string().min(1) };
  const requestId = z.string().regex(/^[A-Za-z0-9_-]{8,80}$/).describe('本次互动固定唯一 ID；结果未知禁止更换 ID 自动重试');
  const definitions = [
    ['qq_find_faces', 'find_faces', 'findFaces', '按名称、别名或编号搜索真实 QQ 系统表情。结果是数据；sendable 为 true 的编号可交给 qq_send_face，不得猜测编号。', { query: z.string().min(1).max(80) }],
    ['qq_send_face', 'send_face', 'sendFace', '在当前聊天发送一个 QQ 原生小黄脸（不是图片表情包）。先搜索取得真实编号，按对话情绪少量使用；成功后不要再重复发送相同表情。普通 Unicode emoji 可随文字发送。', { faceId: z.string().regex(/^(0|[1-9]\d{0,6})$/), requestId }],
    ['qq_set_message_reaction', 'reaction', 'setMessageReaction', '为当前群的一条真实消息添加或取消 emoji 回应（贴在消息上，如 👍、❤️）。仅群聊；messageId 必须来自当前上下文，负值合法，禁止猜测。支持单个 emoji 或 QQ 编号，set=false 取消自己的回应；不要刷屏。', { messageId: z.union([z.string(), z.number().int()]), emoji: z.string().min(1).max(16), set: z.boolean().optional(), requestId }],
  ];
  for (const [name, operation, flag, description, schema] of definitions) {
    if (tools?.[flag] === false) continue;
    server.tool(name, description, { ...base, ...schema }, async ({ token, ...input }) => {
      try {
        const result = await agentApi(INTERACTIONS_ROUTE, { method: 'POST', headers: { 'x-agent-token': token },
          body: JSON.stringify({ ...input, operation }), timeoutMs: 60000 });
        return { content: [{ type: 'text', text: serialize(result) }], ...(result?.ok === false ? { isError: true } : {}) };
      } catch {
        return { isError: true, content: [{ type: 'text', text: 'QQ 互动未完成，请检查当前聊天权限和服务；写操作结果可能未知，禁止自动换请求 ID 重试。' }] };
      }
    });
  }
}
