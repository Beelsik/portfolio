#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const TASKS_DIR = path.join(ROOT, 'tasks');

const ALLOWED_CASES = ['project', 'sales', 'rag', 'docs', 'parser', 'listing', 'hand', 'cc', 'gost', 'spec', 'audit', 'redteam'];
const ALLOWED_KINDS = ['io', 'code', 'ai', 'db', 'human'];

// Conservative character limits per freelance platform so proposals do not truncate
export const PLATFORM_LIMITS = {
  kwork: 900,
  'kwork-en': 900,
  profi: 1500,
  fl: 1500,
  freelancehunt: 1500,
  weblancer: 1500,
  pph: 1500,
  freelancer: 1500,
  codeur: 1200,
  upwork: 1500,
  habr: 1000,
  default: 1200,
};

export const DEFAULT_RU_PORTFOLIO_URL = 'https://beelsik-portfolio-beelsik.mia0.amvera.tech';
export const DEFAULT_EU_PORTFOLIO_URL = 'https://beelsik-portfolio.onrender.com';
export const DEFAULT_UA_PORTFOLIO_URL = 'https://beelsik-portfolio.onrender.com/ua';

function printHelp() {
  console.log(`Usage:
  node scripts/make-task.mjs <slug> --brief "..." [--lang ru|uk|en|fr] [--src kwork|fl|codeur] [--case <id>] [--title "..."] [--push]
  node scripts/make-task.mjs <slug> --file brief.txt [--lang ...] [--src ...] [--push]
  node scripts/make-task.mjs --pitch-only <slug> [--src kwork|fl|codeur|freelancehunt]
  cat brief.txt | node scripts/make-task.mjs <slug> [--src ...] [--push]

Options:
  <slug>        Task ID matching /^[a-z0-9][a-z0-9_-]{0,63}$/i (saved to tasks/<slug>.json)
  --brief       Task brief text inline
  --file        Path to UTF-8 text file containing task brief
  --lang        Target language: ru | uk | en | fr (auto-detected if omitted)
  --src         Source tag for attribution (e.g. kwork, fl, codeur, freelancehunt)
  --case        Related portfolio stand: ${ALLOWED_CASES.join(' | ')}
  --title       Optional override for heading title
  --pitch-only  Print sized pitch for an existing tasks/<slug>.json without writing
  --push        Stage tasks/<slug>.json, commit, and push to origin
  --dry-run     Build structural template offline without LLM call
  --help, -h    Show this help message`);
}

function parseDotEnv(filePath) {
  const env = { ...process.env };
  if (!fs.existsSync(filePath)) return env;
  const raw = fs.readFileSync(filePath, 'utf8');
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const k = trimmed.slice(0, eq).trim();
    let v = trimmed.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (env[k] === undefined || env[k] === '') env[k] = v;
  }
  return env;
}

export function detectLang(text) {
  const s = String(text || '');
  if (/[іїєґІЇЄҐ]/.test(s)) return 'uk';
  if (/[а-яёА-ЯЁ]/.test(s)) return 'ru';
  if (/[éèêàçùûôîâÉÈÊÀÇ]|\b(devis|besoin|facture|société|entreprise|avec|pour)\b/i.test(s)) return 'fr';
  return 'en';
}

export function clipLabel(str, max) {
  const t = String(str || '').trim().replace(/\s+/g, ' ');
  return t.length <= max ? t : t.slice(0, max - 1).trimEnd() + '…';
}

export function encodeTaskZ(obj) {
  const raw = zlib.deflateRawSync(Buffer.from(JSON.stringify(obj), 'utf8'));
  return 'z:' + raw.toString('base64url');
}

export function decodeTaskZ(val) {
  if (!String(val || '').startsWith('z:')) throw new Error('Expected z: prefix');
  const buf = Buffer.from(val.slice(2), 'base64url');
  const out = zlib.inflateRawSync(buf, { maxOutputLength: 32768 });
  return JSON.parse(out.toString('utf8'));
}

function extractJson(text) {
  const cleaned = String(text || '')
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
  const s = cleaned.indexOf('{');
  const e = cleaned.lastIndexOf('}');
  if (s === -1 || e <= s) throw new Error('Model response did not contain valid JSON object');
  const slice = cleaned.slice(s, e + 1);
  try {
    return JSON.parse(slice);
  } catch {
    const fixed = slice.replace(/,\s*([}\]])/g, '$1');
    return JSON.parse(fixed);
  }
}

function parseArgs(argv) {
  const opts = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') opts.help = true;
    else if (a === '--push') opts.push = true;
    else if (a === '--dry-run') opts.dryRun = true;
    else if (a === '--pitch-only') opts.pitchOnly = true;
    else if (a === '--brief' && i + 1 < argv.length) opts.brief = argv[++i];
    else if (a === '--file' && i + 1 < argv.length) opts.file = argv[++i];
    else if (a === '--lang' && i + 1 < argv.length) opts.lang = argv[++i];
    else if (a === '--src' && i + 1 < argv.length) opts.src = argv[++i];
    else if (a === '--case' && i + 1 < argv.length) opts.case = argv[++i];
    else if (a === '--title' && i + 1 < argv.length) opts.title = argv[++i];
    else if (a.startsWith('-')) throw new Error(`Unknown flag: ${a}`);
    else opts.positional.push(a);
  }
  return opts;
}

function b64url(input) {
  return Buffer.from(input).toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
}

async function callVertexDirect(env, system, brief) {
  let creds = null;
  if (env.VERTEX_CREDENTIALS_B64) {
    creds = JSON.parse(Buffer.from(env.VERTEX_CREDENTIALS_B64.trim(), 'base64').toString('utf8'));
  } else if (env.VERTEX_CREDENTIALS_JSON) {
    creds = JSON.parse(env.VERTEX_CREDENTIALS_JSON.trim());
  } else if (env.VERTEX_KEY_FILE && fs.existsSync(env.VERTEX_KEY_FILE.trim())) {
    creds = JSON.parse(fs.readFileSync(env.VERTEX_KEY_FILE.trim(), 'utf8'));
  }
  const projectId = (env.VERTEX_PROJECT_ID || creds?.project_id || '').trim();
  const apiKey = (env.VERTEX_API_KEY || '').trim();
  if (!((creds?.client_email && creds?.private_key && projectId) || apiKey)) return null;

  const model = (env.VERTEX_MODEL || 'gemini-4-neon').trim();
  const loc = (env.VERTEX_LOCATION || 'us').trim();
  const headers = { 'Content-Type': 'application/json' };
  let url = '';

  if (creds?.client_email && projectId) {
    const nowSec = Math.floor(Date.now() / 1000);
    const unsigned = `${b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))}.${b64url(JSON.stringify({
      iss: creds.client_email,
      scope: 'https://www.googleapis.com/auth/cloud-platform',
      aud: creds.token_uri || 'https://oauth2.googleapis.com/token',
      iat: nowSec,
      exp: nowSec + 3600,
    }))}`;
    const signer = crypto.createSign('RSA-SHA256');
    signer.update(unsigned);
    const assertion = `${unsigned}.${signer.sign(creds.private_key).toString('base64url')}`;
    const tokRes = await fetch(creds.token_uri || 'https://oauth2.googleapis.com/token', {
      method: 'POST',
      signal: AbortSignal.timeout(10_000),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion }),
    });
    if (!tokRes.ok) throw new Error(`Vertex OAuth HTTP ${tokRes.status}`);
    const tokJson = await tokRes.json();
    headers.Authorization = `Bearer ${tokJson.access_token}`;
    const host = (env.VERTEX_ENDPOINT || '').trim() || (loc === 'global' ? 'aiplatform.googleapis.com' : (loc === 'us' || loc === 'eu') ? `aiplatform.${loc}.rep.googleapis.com` : `${loc}-aiplatform.googleapis.com`);
    url = `https://${host}/v1beta1/projects/${encodeURIComponent(projectId)}/locations/${encodeURIComponent(loc)}/publishers/google/models/${encodeURIComponent(model)}:generateContent`;
  } else {
    url = `https://aiplatform.googleapis.com/v1beta1/publishers/google/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;
  }

  const isGemini3Or4 = /^gemini-(3|4)/i.test(model);
  const reqBody = JSON.stringify({
    systemInstruction: { parts: [{ text: system }] },
    contents: [{ role: 'user', parts: [{ text: brief }] }],
    generationConfig: {
      temperature: 0.2,
      maxOutputTokens: isGemini3Or4 ? 4096 : 1800,
      responseMimeType: 'application/json',
      ...(isGemini3Or4 ? { thinkingConfig: { thinkingLevel: env.VERTEX_THINKING_LEVEL || 'LOW' } } : {}),
    },
  });
  const candidateLocs = creds?.client_email && projectId && !env.VERTEX_ENDPOINT
    ? [...new Set([loc, 'global', 'eu', 'us'])]
    : [loc];
  let res = null;
  for (let attempt = 0; attempt < Math.min(candidateLocs.length, 3); attempt++) {
    const curLoc = candidateLocs[attempt];
    const reqUrl = creds?.client_email && projectId
      ? (() => {
          const h = (env.VERTEX_ENDPOINT || '').trim() || (curLoc === 'global' ? 'aiplatform.googleapis.com' : (curLoc === 'us' || curLoc === 'eu') ? `aiplatform.${curLoc}.rep.googleapis.com` : `${curLoc}-aiplatform.googleapis.com`);
          return `https://${h}/v1beta1/projects/${encodeURIComponent(projectId)}/locations/${encodeURIComponent(curLoc)}/publishers/google/models/${encodeURIComponent(model)}:generateContent`;
        })()
      : url;
    res = await fetch(reqUrl, {
      method: 'POST',
      signal: AbortSignal.timeout(30_000),
      headers,
      body: reqBody,
    });
    if (res.ok || ![429, 500, 502, 503, 504].includes(res.status)) break;
  }
  if (!res || !res.ok) throw new Error(`Vertex HTTP ${res?.status || 'net'}: ${(await res?.text().catch(() => '') || '').slice(0, 140)}`);
  const data = await res.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  const textPart = parts.find((p) => typeof p.text === 'string' && !p.thought) || parts[0];
  return String(textPart?.text || '').trim();
}

async function callFastDirect(env, system, brief) {
  const provider = (env.LLM_PROVIDER || 'openai').toLowerCase();
  const apiKey = env.LLM_API_KEY || '';
  if (!apiKey && provider !== 'ollama') return null;
  const baseUrl = (env.LLM_BASE_URL || (provider === 'ollama' ? 'http://127.0.0.1:11434/v1' : 'https://api.openai.com/v1')).replace(/\/+$/, '');
  const model = env.LLM_MODEL || 'nvidia/nemotron-3.5-super-vl-120b-a12b';
  const headers = { 'content-type': 'application/json' };
  if (apiKey) headers.authorization = `Bearer ${apiKey}`;
  const payload = {
    model,
    temperature: 0.15,
    max_tokens: 2048,
    messages: [{ role: 'system', content: system }, { role: 'user', content: brief }],
  };
  if (baseUrl.includes('api.openai.com')) {
    payload.response_format = { type: 'json_object' };
  }
  if (/nemotron|qwen|glm/i.test(model) && baseUrl.includes('nvidia.com')) {
    payload.chat_template_kwargs = { enable_thinking: false };
  }
  const res = await fetch(`${baseUrl}/chat/completions`, {
    method: 'POST',
    signal: AbortSignal.timeout(25_000),
    headers,
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`LLM HTTP ${res.status}`);
  const data = await res.json();
  const msg = data.choices?.[0]?.message || {};
  return String(msg.content || msg.reasoning_content || '').trim();
}

function sanitizeSrc(s) {
  return String(s || '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32);
}

export function buildTaskLink(lang, taskVal, src = '') {
  const s = sanitizeSrc(src);
  const srcQ = s ? `src=${encodeURIComponent(s)}&` : '';
  const ruBase = (process.env.RU_PORTFOLIO_URL || DEFAULT_RU_PORTFOLIO_URL).replace(/\/+$/, '');
  const euBase = (process.env.EU_PORTFOLIO_URL || DEFAULT_EU_PORTFOLIO_URL).replace(/\/+$/, '');
  const uaBase = (process.env.UA_PORTFOLIO_URL || DEFAULT_UA_PORTFOLIO_URL).replace(/\/+$/, '');

  if (lang === 'uk' || s === 'freelancehunt') {
    return `${uaBase}?${srcQ}task=${taskVal}`;
  }
  if (lang === 'en' || lang === 'fr' || ['pph', 'freelancer', 'codeur', 'upwork', 'kwork-en'].includes(s)) {
    const langQ = lang === 'fr' ? 'lang=fr&' : lang === 'en' ? 'lang=en&' : '';
    return `${euBase}/?${langQ}${srcQ}task=${taskVal}`;
  }
  return `${ruBase}/?${srcQ}task=${taskVal}`;
}

async function generatePlanWithLlm(env, brief, lang, slug, src = '') {
  const langMap = { ru: 'Russian', uk: 'Ukrainian (strictly pure Ukrainian, zero Russian letters ы/э/ъ/ё/₽)', en: 'English', fr: 'French' };
  const currMap = { ru: 'RUB (₽)', uk: 'UAH (₴)', en: 'USD ($) or GBP (£)', fr: 'EUR (€)' };
  const pageUrl = buildTaskLink(lang, slug, src);
  const system = [
    'You are a pragmatic senior backend & AI automation engineer writing a tailored proposal for a client brief.',
    `Write ALL fields strictly in ${langMap[lang] || 'English'}. Realistic freelance pricing in ${currMap[lang] || 'USD ($)'}.`,
    'Separate deterministic code/SQL/cron (math, checksums, deduplication, permissions, DB writes) from LLM/Vision steps.',
    'Write like a calm, direct human engineer — no marketing fluff or AI clichés.',
    'Keep strings concise (avoid unescaped ASCII double quotes " inside strings — use «» or single quotes).',
    'CRITICAL: Phase 1 milestone MUST say pilot cost is scoped/discussed in chat — NEVER write "free", "бесплатно", or "безкоштовно".',
    'Return ONLY valid JSON with this exact schema:',
    '{',
    '  "title": string (short punchy heading, 6-12 words),',
    '  "summary": string (1-2 crisp sentences separating deterministic code from LLM/OCR),',
    '  "nodes": [{"title": string (max 18 chars), "tech": string (max 21 chars), "kind": "io"|"code"|"ai"|"db"|"human"}] (4 to 6 nodes),',
    '  "split": {"code": string[] (2-3 bullets), "ai": string[] (2 bullets)},',
    '  "milestones": [{"phase": string, "deliverable": string, "estimate": string}] (exactly 3: Pilot -> MVP -> Prod),',
    '  "monthlyOps": string (realistic VPS + token estimate per month),',
    '  "questions": string[] (exactly 3 sharp technical kickoff questions),',
    `  "relatedCase": one of ${JSON.stringify(ALLOWED_CASES)},`,
    `  "pitch": string (2-3 sentence friendly freelance reply including link ${pageUrl})`,
    '}',
  ].join('\n');

  try {
    const rawVertex = await callVertexDirect(env, system, brief);
    if (rawVertex) return extractJson(rawVertex);
  } catch (err) {
    console.error(`[make-task] Vertex attempt failed (${err.message}), trying Fast tier...`);
  }
  const rawFast = await callFastDirect(env, system, brief);
  if (rawFast) {
    try {
      return extractJson(rawFast);
    } catch {
      const retryRaw = await callFastDirect(env, system + '\nStrictly valid RFC 8259 JSON only. Escape all quotes properly.', brief);
      if (retryRaw) return extractJson(retryRaw);
    }
  }

  // Fallback to local running server.mjs /api/scope
  const localUrl = `http://127.0.0.1:${env.PORT || 3000}/api/scope`;
  const r = await fetch(localUrl, {
    method: 'POST',
    signal: AbortSignal.timeout(25_000),
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ brief, lang }),
  });
  if (!r.ok) throw new Error(`No API key in .env and local ${localUrl} returned HTTP ${r.status}`);
  return await r.json();
}

function buildDryRunPlan(brief, lang, slug, src = '') {
  const link = buildTaskLink(lang, slug, src);
  const templates = {
    ru: {
      title: `Разбор задачи: ${clipLabel(brief, 56)}`,
      summary: 'Забор данных, расчёты, права доступа и запись в базу остаются в обычном проверяемом коде на Python; модель подключается только там, где плавает формат текста или документов.',
      nodes: [
        { title: 'Вход и вебхук', tech: 'FastAPI Worker', kind: 'io' },
        { title: 'Разбор текста', tech: 'LLM / OCR JSON', kind: 'ai' },
        { title: 'Сверка правил', tech: 'Python + Decimal', kind: 'code' },
        { title: 'Очередь спорных', tech: 'Telegram Review', kind: 'human' },
        { title: 'Запись в базу', tech: 'CRM / PostgreSQL', kind: 'db' },
      ],
      split: {
        code: ['Забор входных событий с фильтром дублей', 'Проверка чисел, дат, прав доступа и формата полей до записи', 'Идемпотентная запись в целевую CRM/БД с ретраями и логом'],
        ai: ['Извлечение структуры из неформализованного текста, писем и сканов', 'Сопоставление свободных формулировок со справочником'],
      },
      milestones: [
        { phase: '1. Пилот на 10–15 файлах', deliverable: 'Прогон на обезличенной выборке и замер точности', estimate: '1–2 дня · обсудим в переписке' },
        { phase: '2. Рабочий MVP', deliverable: 'Основной конвейер разбора, проверки правил и записи в базу', estimate: '1,5–2 недели · 45 000 – 65 000 ₽' },
        { phase: '3. Прод и тесты', deliverable: 'Очередь спорных кейсов, Docker на вашем VPS и автотесты', estimate: '4–5 дней · 20 000 ₽' },
      ],
      monthlyOps: 'VPS (~1 000 ₽/мес) + токены API под умеренную нагрузку (~1 000 – 2 000 ₽/мес).',
      questions: ['Где сейчас хранится источник данных и целевая система учёта (API / БД)?', 'Допустим ли облачный API модели или нужен закрытый контур на своём сервере?', 'Какие поля считаются критичными, чтобы ставить документ на ручное подтверждение?'],
      relatedCase: 'project',
      pitch: `Здравствуйте! Набросал предварительную архитектуру под вашу задачу (схема конвейера, этапы и 3 вопроса): ${link}`,
    },
    uk: {
      title: `Розбір задачі: ${clipLabel(brief, 56)}`,
      summary: 'Забір даних, розрахунки, права доступу та запис у базу виконуються звичайним кодом на Python; модель підключається лише там, де текст чи документи не мають жорсткого формату.',
      nodes: [
        { title: 'Вхідні дані', tech: 'FastAPI Worker', kind: 'io' },
        { title: 'Розбір тексту', tech: 'LLM / OCR JSON', kind: 'ai' },
        { title: 'Перевірка правил', tech: 'Python + Decimal', kind: 'code' },
        { title: 'Черга спірних', tech: 'Telegram Review', kind: 'human' },
        { title: 'Запис у систему', tech: 'CRM / PostgreSQL', kind: 'db' },
      ],
      split: {
        code: ['Забір вхідних подій із фільтром дублів', 'Перевірка чисел, дат, прав доступу та форматів до запису', 'Ідемпотентний запис у CRM/БД із логуванням'],
        ai: ['Витяг структури з неформалізованого тексту, листів і сканів', 'Зіставлення вільних назв із вашим довідником'],
      },
      milestones: [
        { phase: '1. Пілот на 10–15 файлах', deliverable: 'Прогін на знеособленій вибірці та оцінка точності', estimate: '1–2 дні · обговоримо в переписці' },
        { phase: '2. Робочий MVP', deliverable: 'Основний конвеєр розбору, перевірки правил і запису в систему', estimate: '1,5–2 тижні · 35 000 – 50 000 ₴' },
        { phase: '3. Прод та тести', deliverable: 'Черга спірних рядків, Docker на сервері й автотести', estimate: '4–5 днів · 18 000 ₴' },
      ],
      monthlyOps: 'VPS у ЄС (~600–900 ₴/міс) + витрати на API (~700–1 500 ₴/міс).',
      questions: ['Яка система є джерелом даних та куди записувати результат (API / БД)?', 'Чи можна використовувати хмарний LLM API, чи потрібен локальний сервер?', 'За яких розбіжностей варто зупиняти запис для перевірки оператором?'],
      relatedCase: 'rag',
      pitch: `Вітаю! Підготував попередню архітектуру під вашу задачу (схема конвеєра, етапи й питання): ${link}`,
    },
    en: {
      title: `Architecture Plan: ${clipLabel(brief, 52)}`,
      summary: 'Ingestion, arithmetic checks, permissions, and database writes stay in deterministic Python code; LLMs are scoped strictly to unstructured input parsing and fuzzy matching.',
      nodes: [
        { title: 'Inbound Trigger', tech: 'FastAPI Worker', kind: 'io' },
        { title: 'Unstructured Parse', tech: 'LLM / Vision JSON', kind: 'ai' },
        { title: 'Deterministic Guard', tech: 'Python + Rules', kind: 'code' },
        { title: 'Exception Queue', tech: 'Operator Review', kind: 'human' },
        { title: 'Target Sync', tech: 'PostgreSQL / API', kind: 'db' },
      ],
      split: {
        code: ['Idempotent input ingestion and deduplication', 'Strict schema, math, and permission checks before persistence', 'Transactional API/database sync with audit logging'],
        ai: ['Extracting structured records from messy emails, docs, or scans', 'Proposing catalog/entity matches with confidence scores'],
      },
      milestones: [
        { phase: '1. Pilot on 10–15 samples', deliverable: 'Benchmark accuracy on anonymized real inputs', estimate: '1–2 days · scoped in chat' },
        { phase: '2. Core MVP', deliverable: 'End-to-end ingestion, validation rules, and target integration', estimate: '2 weeks · $900 – $1,300' },
        { phase: '3. Production & Tests', deliverable: 'Exception UI, Docker deployment, and automated test suite', estimate: '1 week · $450' },
      ],
      monthlyOps: 'Cloud VPS ($12–$18/mo) + LLM tokens at moderate volume (~$15–$30/mo).',
      questions: ['Which API/database holds the source of truth and receives validated writes?', 'Can anonymized payloads use cloud LLM APIs or must models run locally?', 'Which confidence or value mismatch thresholds should route items to manual review?'],
      relatedCase: 'docs',
      pitch: `Hi! I drafted an architecture breakdown tailored to your brief (pipeline schematic, milestones, and kickoff questions): ${link}`,
    },
  };
  return templates[lang] || templates.en;
}

function sanitizePilotEstimate(est, lang) {
  const s = String(est || '').trim();
  const replacement = {
    ru: '1–2 дня · обсудим в переписке',
    uk: '1–2 дні · обговоримо в переписці',
    fr: '1–2 jours · à définir ensemble',
    en: '1–2 days · scoped in chat',
  }[lang] || '1–2 days · scoped in chat';
  if (!s || /(бесплатн|безкоштовн|\bfree\b|gratuit|\$0\b|0\s*[₽₴€])/i.test(s)) return replacement;
  return s;
}

function normalizeTaskObject({ rawPlan, slug, brief, lang, titleOverride, caseOverride, src = '' }) {
  const rawNodes = Array.isArray(rawPlan.nodes) ? rawPlan.nodes.slice(0, 6) : [];
  while (rawNodes.length < 4) {
    rawNodes.push({ title: 'Python Check', tech: 'FastAPI / SQL', kind: 'code' });
  }
  const nodes = rawNodes.map((n) => ({
    title: clipLabel(n.title || 'Step', 19),
    tech: clipLabel(n.tech || 'Python', 22),
    kind: ALLOWED_KINDS.includes(n.kind) ? n.kind : 'code',
  }));

  const milestones = (Array.isArray(rawPlan.milestones) ? rawPlan.milestones : []).slice(0, 3);
  if (milestones[0]) {
    milestones[0] = {
      phase: String(milestones[0].phase || '1. Pilot').replace(/(бесплатн\w*|безкоштовн\w*|\bfree\b|gratuit)/gi, '').trim() || '1. Pilot',
      deliverable: String(milestones[0].deliverable || '').replace(/(бесплатн\w*|безкоштовн\w*|\bfree\b|gratuit)/gi, '').trim(),
      estimate: sanitizePilotEstimate(milestones[0].estimate, lang),
    };
  }
  while (milestones.length < 3) {
    milestones.push({ phase: `${milestones.length + 1}. Stage`, deliverable: 'Delivery & verification', estimate: 'TBD' });
  }

  let rc = String(caseOverride || rawPlan.relatedCase || 'project').trim();
  if (!ALLOWED_CASES.includes(rc)) rc = 'project';
  if (lang === 'uk' && rc === 'gost') rc = 'spec';
  if (lang !== 'uk' && rc === 'spec') rc = 'gost';

  const cleanSrc = sanitizeSrc(src);
  const srcQ = cleanSrc ? `src=${encodeURIComponent(cleanSrc)}&` : '';
  const link = buildTaskLink(lang, slug, cleanSrc);
  const defaultTitle = lang === 'uk' ? `Розбір задачі: ${clipLabel(brief, 56)}` : lang === 'ru' ? `Разбор задачи: ${clipLabel(brief, 56)}` : `Architecture Plan: ${clipLabel(brief, 52)}`;
  let pitchRaw = String(rawPlan.pitch || '').trim();
  if (cleanSrc && pitchRaw && !pitchRaw.includes(`src=${cleanSrc}`)) {
    pitchRaw = pitchRaw.replace(new RegExp(`\\?task=${slug}\\b`, 'g'), `?${srcQ}task=${slug}`);
  }
  const pitch = pitchRaw ? (pitchRaw.includes(slug) ? pitchRaw : `${pitchRaw} ${link}`) : `${link}`;

  const task = {
    slug,
    lang,
    createdAt: new Date().toISOString().slice(0, 10),
    title: String(titleOverride || rawPlan.title || defaultTitle).trim(),
    brief: String(brief || '').trim(),
    summary: String(rawPlan.summary || '').trim(),
    nodes,
    split: {
      code: Array.isArray(rawPlan.split?.code) ? rawPlan.split.code.slice(0, 4).map(String) : [],
      ai: Array.isArray(rawPlan.split?.ai) ? rawPlan.split.ai.slice(0, 4).map(String) : [],
    },
    milestones,
    monthlyOps: String(rawPlan.monthlyOps || '').trim(),
    questions: Array.isArray(rawPlan.questions) ? rawPlan.questions.slice(0, 3).map(String) : [],
    relatedCase: rc,
    pitch,
  };

  if (lang === 'uk') {
    const serialized = JSON.stringify(task);
    if (/[ыэъёЫЭЪЁ₽]/.test(serialized)) {
      throw new Error('Generated Ukrainian task contained Russian characters (ы/э/ъ/ё/₽). Re-run or adjust prompt.');
    }
  }
  return task;
}

export function buildPlatformPitch({ task, src = '', link = '' }) {
  const sSrc = sanitizeSrc(src) || 'default';
  const limit = PLATFORM_LIMITS[sSrc] || PLATFORM_LIMITS.default;
  const lang = task?.lang || 'ru';
  const firstCode = String(task?.split?.code?.[0] || '').trim();
  const question = String(task?.questions?.[0] || '').trim();
  const rawSummary = String(task?.summary || '').trim().replace(/\s+/g, ' ');
  const firstSentence = (rawSummary.split(/(?<=[.!?])\s+/)[0] || rawSummary).trim();
  const resolvedLink = link || buildTaskLink(lang, task?.slug || 'custom-order', src);

  const tpl = {
    ru: {
      hook: 'Здравствуйте! Посмотрел ваше ТЗ: ',
      link: `Набросал схему, этапы и цены под вашу задачу: ${resolvedLink}`,
    },
    uk: {
      hook: 'Вітаю! Переглянув ваше ТЗ: ',
      link: `Підготував схему, етапи та ціни під вашу задачу: ${resolvedLink}`,
    },
    fr: {
      hook: 'Bonjour ! J’ai lu votre besoin : ',
      link: `J’ai préparé le schéma, les étapes et les tarifs pour votre projet : ${resolvedLink}`,
    },
    en: {
      hook: 'Hi! Read your brief: ',
      link: `I mapped out the pipeline, milestones, and pricing for your task: ${resolvedLink}`,
    },
  }[lang] || {
    hook: 'Hi! Read your brief: ',
    link: `I mapped out the pipeline, milestones, and pricing for your task: ${resolvedLink}`,
  };

  const partA = `${tpl.hook}${firstSentence}`;
  const partB = tpl.link;
  const partC = firstCode;
  const partD = question;

  let text = [partA, partB, partC, partD].filter(Boolean).join('\n\n');
  if (text.length > limit) {
    text = [partA, partB, partD].filter(Boolean).join('\n\n');
  }
  if (text.length > limit) {
    const fixedSuffix = [partB, partD].filter(Boolean).join('\n\n');
    const overhead = tpl.hook.length + (fixedSuffix ? 3 + fixedSuffix.length : 1); // '…\n\n'
    const avail = Math.max(0, limit - overhead);
    const trimmed = avail > 0 ? firstSentence.slice(0, avail).trimEnd() + '…' : '…';
    const shortA = `${tpl.hook}${trimmed}`.trim();
    text = [shortA, fixedSuffix].filter(Boolean).join('\n\n');
  }
  if (text.length > limit) {
    text = [partB, partD].filter(Boolean).join('\n\n');
  }
  return { text, limit, length: text.length };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    process.exit(0);
  }
  const slug = opts.positional[0];
  if (!slug || !/^[a-z0-9][a-z0-9_-]{0,63}$/i.test(slug)) {
    throw new Error('Provide a valid <slug> matching /^[a-z0-9][a-z0-9_-]{0,63}$/i. Run with --help for usage.');
  }

  const src = sanitizeSrc(opts.src);
  if (opts.pitchOnly) {
    const existingPath = path.join(TASKS_DIR, `${slug}.json`);
    if (!fs.existsSync(existingPath)) {
      throw new Error(`Task file not found: ${existingPath}`);
    }
    const existingTask = JSON.parse(fs.readFileSync(existingPath, 'utf8'));
    const link = buildTaskLink(existingTask.lang || 'ru', slug, src);
    const pitched = buildPlatformPitch({ task: existingTask, src, link });
    const srcLabel = src || 'default';
    console.log(`\nPitch for ${srcLabel} (${pitched.length}/${pitched.limit} chars):\n${pitched.text}\n`);
    if (src === 'kwork') {
      console.log('Kwork может модерировать внешние ссылки — при отказе оставьте ссылку в портфолио профиля.\n');
    }
    return;
  }

  let brief = opts.brief || '';
  if (!brief && opts.file) brief = fs.readFileSync(path.resolve(opts.file), 'utf8');
  if (!brief && !process.stdin.isTTY) brief = fs.readFileSync(0, 'utf8');
  brief = String(brief || '').trim();
  if (!brief) throw new Error('Task brief is required via --brief, --file, or stdin.');

  const lang = ['ru', 'uk', 'en', 'fr'].includes(opts.lang) ? opts.lang : detectLang(brief);
  const env = parseDotEnv(path.join(ROOT, '.env'));

  const rawPlan = opts.dryRun
    ? buildDryRunPlan(brief, lang, slug, src)
    : await generatePlanWithLlm(env, brief, lang, slug, src);

  const task = normalizeTaskObject({
    rawPlan,
    slug,
    brief,
    lang,
    titleOverride: opts.title,
    caseOverride: opts.case,
    src,
  });

  fs.mkdirSync(TASKS_DIR, { recursive: true });
  const outPath = path.join(TASKS_DIR, `${slug}.json`);
  fs.writeFileSync(outPath, JSON.stringify(task, null, 2) + '\n', 'utf8');

  const srcQ = src ? `src=${encodeURIComponent(src)}&` : '';
  const primaryUrl = buildTaskLink(lang, slug, src);
  const amveraBase = (process.env.RU_PORTFOLIO_URL || DEFAULT_RU_PORTFOLIO_URL).replace(/\/+$/, '');
  const renderBase = (process.env.EU_PORTFOLIO_URL || DEFAULT_EU_PORTFOLIO_URL).replace(/\/+$/, '');
  const amveraUrl = `${amveraBase}${lang === 'uk' ? `/ua?${srcQ}task=${slug}` : `/?${srcQ}task=${slug}`}`;
  const renderUrl = `${renderBase}${lang === 'uk' ? `/ua?${srcQ}task=${slug}` : `/?${lang === 'en' || lang === 'fr' ? `lang=${lang}&` : ''}${srcQ}task=${slug}`}`;
  const zPayload = encodeTaskZ(task);
  const zUrl = buildTaskLink(lang, zPayload, src);

  if (opts.push) {
    execFileSync('git', ['add', `tasks/${slug}.json`], { cwd: ROOT, stdio: 'inherit' });
    execFileSync('git', ['commit', '-m', `Add task proposal: ${slug}`], { cwd: ROOT, stdio: 'inherit' });
    execFileSync('git', ['pull', '--rebase', '--autostash', 'origin', 'main'], { cwd: ROOT, stdio: 'inherit' });
    execFileSync('git', ['push', 'origin', 'main'], { cwd: ROOT, stdio: 'inherit' });
    try {
      const remotes = execFileSync('git', ['remote'], { cwd: ROOT, encoding: 'utf8' })
        .split(/\r?\n/)
        .map((r) => r.trim());
      if (remotes.includes('amvera')) {
        execFileSync('git', ['push', 'amvera', 'main:master'], { cwd: ROOT, stdio: 'inherit' });
      }
    } catch (err) {
      console.warn(`[make-task warn] Amvera push skipped/failed: ${err.message}`);
    }
  }

  console.log(`\nSaved: ${outPath}`);
  console.log(`Regional target URL:    ${primaryUrl}`);
  console.log(`Amvera URL (RU fast):   ${amveraUrl}`);
  console.log(`Render URL (EU/UA):     ${renderUrl}`);
  console.log(`Zero-deploy (?task=z:): ${zUrl.slice(0, 120)}${zUrl.length > 120 ? `... (${zUrl.length} chars)` : ''}`);
  if (src) {
    const pitched = buildPlatformPitch({ task, src, link: primaryUrl });
    console.log(`\nPitch for ${src} (${pitched.length}/${pitched.limit} chars):\n${pitched.text}\n`);
    if (src === 'kwork') {
      console.log('Kwork может модерировать внешние ссылки — при отказе оставьте ссылку в портфолио профиля.\n');
    }
  } else {
    console.log(`\nPitch:\n${task.pitch}\n`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  main().catch((err) => {
    console.error(`[make-task error] ${err.message}`);
    process.exit(1);
  });
}
