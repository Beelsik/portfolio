import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);

const LLM_PROVIDER = (process.env.LLM_PROVIDER || 'openai').toLowerCase(); // openai | anthropic | gemini | ollama
const LLM_API_KEY = process.env.LLM_API_KEY || '';
const LLM_BASE_URL = (
  process.env.LLM_BASE_URL ||
  (LLM_PROVIDER === 'ollama'
    ? 'http://host.docker.internal:11434/v1'
    : LLM_PROVIDER === 'anthropic'
      ? 'https://api.anthropic.com'
      : LLM_PROVIDER === 'gemini'
        ? 'https://generativelanguage.googleapis.com'
        : 'https://api.openai.com/v1')
).replace(/\/+$/, '');

const LLM_MODEL =
  process.env.LLM_MODEL ||
  (LLM_PROVIDER === 'anthropic'
    ? 'claude-3-5-haiku-latest'
    : LLM_PROVIDER === 'gemini'
      ? 'gemini-2.5-flash'
      : LLM_PROVIDER === 'ollama'
        ? 'qwen2.5:7b'
        : 'nvidia/nemotron-3.5-super-vl-120b-a12b');

const LLM_VISION_MODEL =
  process.env.LLM_VISION_MODEL ||
  (LLM_BASE_URL.includes('nvidia.com') ? 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning' : LLM_MODEL);

const LLM_ENABLED = LLM_PROVIDER === 'ollama' || Boolean(LLM_API_KEY);
const VISION_ENABLED = LLM_ENABLED;

// Per-IP rate limiter so public demo endpoints stay safe
const hits = new Map();
const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_MAX = Number(process.env.RATE_LIMIT_MAX || 60);

function checkRateLimit(ip) {
  const now = Date.now();
  const list = (hits.get(ip) || []).filter((ts) => now - ts < RATE_WINDOW_MS);
  if (list.length >= RATE_MAX) return false;
  list.push(now);
  hits.set(ip, list);
  return true;
}

function readJsonBody(req, maxBytes = 4 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > maxBytes) {
        req.destroy();
        reject(new Error('Payload too large (max 4 MB)'));
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8');
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

function extractJson(text) {
  const cleaned = String(text || '')
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
  const objStart = cleaned.indexOf('{');
  const arrStart = cleaned.indexOf('[');
  let start = -1;
  let end = -1;
  if (arrStart !== -1 && (objStart === -1 || arrStart < objStart)) {
    start = arrStart;
    end = cleaned.lastIndexOf(']');
  } else if (objStart !== -1) {
    start = objStart;
    end = cleaned.lastIndexOf('}');
  }
  if (start === -1 || end === -1 || end <= start) {
    throw new Error('Model did not return valid JSON');
  }
  return JSON.parse(cleaned.slice(start, end + 1));
}

async function callLLM({ system, messages, maxTokens = 700, jsonMode = false, vision = false, timeoutMs = 28000 }) {
  if (!LLM_ENABLED) throw new Error('LLM not configured');
  const model = vision ? LLM_VISION_MODEL : LLM_MODEL;

  if (LLM_PROVIDER === 'anthropic') {
    const mapped = messages.map((m) => {
      if (Array.isArray(m.content)) {
        return {
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content.map((part) => {
            if (part.type === 'image_url') {
              const [, mediaType, data] = String(part.image_url?.url || '').match(/^data:(image\/[^;]+);base64,(.+)$/) || [];
              return { type: 'image', source: { type: 'base64', media_type: mediaType || 'image/jpeg', data: data || '' } };
            }
            return { type: 'text', text: part.text || '' };
          }),
        };
      }
      return { role: m.role === 'assistant' ? 'assistant' : 'user', content: String(m.content || '') };
    });

    const res = await fetch(`${LLM_BASE_URL}/v1/messages`, {
      method: 'POST',
      signal: AbortSignal.timeout(timeoutMs),
      headers: {
        'content-type': 'application/json',
        'x-api-key': LLM_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({ model, max_tokens: maxTokens, temperature: 0.2, system, messages: mapped }),
    });
    if (!res.ok) throw new Error(`Anthropic HTTP ${res.status}`);
    const data = await res.json();
    return data.content?.[0]?.text || '';
  }

  if (LLM_PROVIDER === 'gemini') {
    const url = `${LLM_BASE_URL}/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(LLM_API_KEY)}`;
    const contents = messages.map((m) => {
      const parts = Array.isArray(m.content)
        ? m.content.map((p) => {
            if (p.type === 'image_url') {
              const [, mimeType, data] = String(p.image_url?.url || '').match(/^data:(image\/[^;]+);base64,(.+)$/) || [];
              return { inlineData: { mimeType: mimeType || 'image/jpeg', data: data || '' } };
            }
            return { text: p.text || '' };
          })
        : [{ text: String(m.content || '') }];
      return { role: m.role === 'assistant' ? 'model' : 'user', parts };
    });

    const res = await fetch(url, {
      method: 'POST',
      signal: AbortSignal.timeout(timeoutMs),
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents,
        generationConfig: {
          temperature: 0.2,
          maxOutputTokens: maxTokens,
          ...(jsonMode ? { responseMimeType: 'application/json' } : {}),
        },
      }),
    });
    if (!res.ok) throw new Error(`Gemini HTTP ${res.status}`);
    const data = await res.json();
    return data.candidates?.[0]?.content?.parts?.[0]?.text || '';
  }

  // OpenAI-compatible (NVIDIA NIM, OpenAI, OpenRouter, DeepSeek, Groq, Ollama)
  const headers = { 'content-type': 'application/json' };
  if (LLM_API_KEY) headers.authorization = `Bearer ${LLM_API_KEY}`;

  const payload = {
    model,
    temperature: 0.15,
    max_tokens: maxTokens,
    messages: [{ role: 'system', content: system }, ...messages],
  };

  if (jsonMode && LLM_BASE_URL.includes('api.openai.com')) {
    payload.response_format = { type: 'json_object' };
  }
  // Disable verbose chain-of-thought on NVIDIA Nemotron reasoning models so replies stay fast (<1.5s) and clean
  if (/nemotron|qwen|glm/i.test(model) && LLM_BASE_URL.includes('nvidia.com')) {
    payload.chat_template_kwargs = { enable_thinking: false };
  }

  const res = await fetch(`${LLM_BASE_URL}/chat/completions`, {
    method: 'POST',
    signal: AbortSignal.timeout(timeoutMs),
    headers,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errBody = await res.text().catch(() => '');
    throw new Error(`LLM HTTP ${res.status}${errBody ? ': ' + errBody.slice(0, 140) : ''}`);
  }
  const data = await res.json();
  const msg = data.choices?.[0]?.message || {};
  return String(msg.content || msg.reasoning_content || '').trim();
}

const server = http.createServer(async (req, res) => {
  const urlPath = (req.url || '/').split('?')[0];

  if (req.method === 'GET' && (urlPath === '/ua' || urlPath === '/ua/' || urlPath === '/ua.html')) {
    const filePath = path.join(__dirname, 'ua.html');
    fs.readFile(filePath, (err, buf) => {
      if (err) {
        res.writeHead(404);
        res.end('Not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(buf);
    });
    return;
  }

  if (req.method === 'GET' && (urlPath === '/' || urlPath === '/index.html' || urlPath === '/portfolio.html')) {
    const filePath = path.join(__dirname, 'index.html');
    fs.readFile(filePath, (err, buf) => {
      if (err) {
        res.writeHead(404);
        res.end('Not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(buf);
    });
    return;
  }

  if (req.method === 'GET' && urlPath === '/api/health') {
    sendJson(res, 200, {
      ok: true,
      llmEnabled: LLM_ENABLED,
      visionEnabled: VISION_ENABLED,
      provider: LLM_ENABLED ? LLM_PROVIDER : 'local',
      model: LLM_ENABLED ? LLM_MODEL : 'deterministic',
      visionModel: VISION_ENABLED ? LLM_VISION_MODEL : 'none',
    });
    return;
  }

  if (req.method === 'POST' && urlPath.startsWith('/api/')) {
    const ip = req.headers['x-forwarded-for']?.toString().split(',')[0].trim() || req.socket.remoteAddress || 'local';
    if (!checkRateLimit(ip)) {
      sendJson(res, 429, { error: 'Rate limit exceeded for demo session. Try again shortly.' });
      return;
    }
    if (!LLM_ENABLED) {
      sendJson(res, 503, { error: 'LLM API key is not configured in .env' });
      return;
    }

    try {
      const body = await readJsonBody(req);

      const langName = (code) => ({ uk: 'Ukrainian', en: 'English', fr: 'French', ru: 'Russian' }[code] || 'English');

      /* 01 — CLINIC CHAT AGENT */
      if (urlPath === '/api/chat') {
        const { messages = [], kb = {}, bookedSlots = [], lang = 'ru' } = body;
        const system = [
          'You are the front-desk AI assistant for a dental clinic in a live portfolio demo.',
          'All human operators are currently busy, so you handle incoming inquiries.',
          `Reply in the customer's language (default language: ${langName(lang)}), concise and natural (max 3 sentences).`,
          'STRICT RULES:',
          '- Use ONLY facts from the Knowledge Base JSON below. Never invent prices, doctors, discounts, or policies.',
          `- Already booked slots (UNAVAILABLE, do not offer these): ${JSON.stringify(bookedSlots)}.`,
          '- If the user asks about insurance (страховка / ДМС / mutuelle), installment plans, sedation/narcosis, or anything not in the KB, DO NOT guess: explain briefly and set action.type = "handoff".',
          '- To book a slot, you need service, an available slot, client name, and phone number. Once all four are present, confirm the booking and set action.type = "lead".',
          `Knowledge Base JSON:\n${JSON.stringify(kb)}`,
          'Return ONLY valid JSON: {"reply": string, "action": {"type": "none"|"lead"|"handoff", "name"?: string, "phone"?: string, "service"?: string, "slot"?: string, "reason"?: string}}',
        ].join('\n');

        const raw = await callLLM({ system, messages: messages.slice(-10), maxTokens: 420, jsonMode: true });
        sendJson(res, 200, extractJson(raw));
        return;
      }

      /* 02 — RAG SYNTHESIS */
      if (urlPath === '/api/rag') {
        const { query = '', chunks = [], role = 'staff', lang = 'ru' } = body;
        if (!chunks.length) {
          sendJson(res, 200, { answer: null });
          return;
        }
        const ctx = chunks.map((c) => `[${c.id}] (${c.src}) ${c.text}`).join('\n');
        const system = [
          `You are a corporate knowledge-base assistant. Current user role: ${role}.`,
          `Answer the question in its own language (default: ${langName(lang)}) in 1-3 concise sentences using ONLY the retrieved fragments below.`,
          'Cite every fact inline as [D#]. Never use outside knowledge.',
          'If the fragments do not answer the question, state honestly that nothing was found in accessible sources.',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: `Fragments:\n${ctx}\n\nQuestion: ${query}` }],
          maxTokens: 320,
        });
        sendJson(res, 200, { answer: raw.trim() });
        return;
      }

      /* 03 — MULTI-DOCUMENT EXTRACTION & CROSS-CHECK */
      if (urlPath === '/api/docs') {
        const { srcA = '', srcB = '', lang = 'ru' } = body;
        const system = [
          'Extract contract fields from two business documents (Source A: company card / details, Source B: invoice / quote) and cross-check them strictly.',
          `Write field labels and validation notes in ${langName(lang)}.`,
          'Recalculate every line item (qty * unit price) and compare the sum with the stated total. Compare company name, tax ID (ЄДРПОУ/INN/SIRET/VAT), bank account/IBAN between A and B.',
          'Never silently fix mismatches — flag them with level "bad" (real mismatch/math error) or "warn" (minor formatting difference).',
          'Return ONLY valid JSON array of objects: [{"key":"name|inn|kpp|addr|bank|signer|subj|total|term", "label": string, "val": string, "note": string, "level": "ok"|"warn"|"bad"}]',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: `Source A:\n${String(srcA).slice(0, 3500)}\n\nSource B:\n${String(srcB).slice(0, 3500)}` }],
          maxTokens: 900,
          jsonMode: true,
        });
        const parsed = extractJson(raw);
        const fields = Array.isArray(parsed) ? parsed : Array.isArray(parsed.fields) ? parsed.fields : [];
        sendJson(res, 200, { fields });
        return;
      }

      /* 04 — BOM / SPECIFICATION PARSER & CATALOG MATCHER */
      if (urlPath === '/api/parse') {
        const { lines = [], catalog = [], lang = 'ru' } = body;
        const system = [
          'You match messy procurement / BOM specification lines against a master supplier catalog.',
          'For each input line: extract quantity (number, default 1), match to the closest SKU in the catalog (handle typos, x/*/х, mm2/мм², units).',
          'Confidence levels: "ok" (exact spec match), "warn" (close analog — note what differs), "bad" (not in catalog -> sku: "MANUAL-CHECK", price: 0).',
          `Write names/notes for unmatched items in ${langName(lang)}.`,
          'Return ONLY valid JSON: {"rows":[{"raw":string,"sku":string,"name":string,"qty":number,"unit":string,"price":number,"conf":"ok"|"warn"|"bad"}]}',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: `Catalog:\n${JSON.stringify(catalog)}\n\nInput lines:\n${lines.slice(0, 20).join('\n')}` }],
          maxTokens: 950,
          jsonMode: true,
        });
        sendJson(res, 200, extractJson(raw));
        return;
      }

      /* 05 — MARKETPLACE LISTING BUILDER */
      if (urlPath === '/api/listing') {
        const { note = '', marketplace = 'ebay' } = body;
        const mpRule =
          marketplace === 'wb'
            ? 'Write a Wildberries / Ozon product card in Russian. Title <= 60 characters, keyword-rich, no caps/spam.'
            : marketplace === 'prom'
              ? 'Write a Rozetka / Prom.ua product listing in Ukrainian. Title <= 70 characters, keyword-rich, honest about condition.'
              : marketplace === 'vinted'
                ? 'Write a Vinted / Leboncoin listing in French. Title <= 70 characters, honest about flaws.'
                : 'Write an eBay UK/US listing in English. Title <= 80 characters, keyword-first, no ALL CAPS, no !!!.';
        const system = [
          mpRule,
          'Use ONLY facts present in the note. Never invent specs, brands, or warranties.',
          'Return ONLY valid JSON:',
          '{"title": string, "category": string, "conditionEnum": "NEW"|"USED_GOOD", "specifics": object, "paragraphs": string[] (3-4 honest plain-text paragraphs)}',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: String(note).slice(0, 1500) }],
          maxTokens: 550,
          jsonMode: true,
        });
        sendJson(res, 200, extractJson(raw));
        return;
      }

      /* 06 — VISION OCR (UPLOADED PHOTO / CANVAS SCAN) */
      if (urlPath === '/api/ocr') {
        const { imageDataUrl = '', mode = 'verbatim', lang = 'ru' } = body;
        if (!/^data:image\/(png|jpeg|jpg|webp);base64,/i.test(imageDataUrl)) {
          sendJson(res, 400, { error: 'Expected base64 image data URL (PNG/JPEG/WebP)' });
          return;
        }
        const prompt =
          mode === 'invoice'
            ? 'Extract all text, company details, line items, numbers, and totals from this document image cleanly as plain text preserving line breaks. Do not add commentary.'
            : mode === 'norm'
              ? 'Transcribe the text from this handwritten or printed image into clean, normalized readable text (fix obvious spelling/punctuation, omit crossed-out words), keeping [illegible] for genuinely unreadable smudges. Output ONLY the transcription.'
              : 'Transcribe the text in this image VERBATIM (diplomatic transcription). Rules: preserve exact original spelling errors, capitalization, and punctuation; represent crossed-out words as ~~word~~; if any word is obscured/smudged/unreadable write [illegible] — NEVER guess; preserve line breaks. Output ONLY the transcription without markdown code fences or commentary.';

        const raw = await callLLM({
          system: `You are a precise archival & document Vision OCR engine (UI language: ${langName(lang)}). Never hallucinate unreadable text.`,
          messages: [
            {
              role: 'user',
              content: [
                { type: 'text', text: prompt },
                { type: 'image_url', image_url: { url: imageDataUrl } },
              ],
            },
          ],
          maxTokens: 800,
          vision: true,
          timeoutMs: 30000,
        });
        sendJson(res, 200, { text: raw.replace(/^```[\w-]*\s*/i, '').replace(/\s*```$/, '').trim(), model: LLM_VISION_MODEL });
        return;
      }

      /* 08 — TECHNICAL SPEC / UAT TEST CASE GENERATOR */
      if (urlPath === '/api/gost') {
        const { requirement = '', lang = 'ru' } = body;
        const stdHint = lang === 'ru' ? 'GOST R 59792 / GOST 34 ПМИ' : lang === 'uk' ? 'ДСТУ / ISO 29148 ПМІ' : 'ISO/IEC 29148 UAT acceptance test';
        const codePrefix = lang === 'ru' ? 'ПМИ-24' : lang === 'uk' ? 'ПМІ-24' : lang === 'fr' ? 'REC-24' : 'UAT-24';
        const system = [
          `You are a senior systems analyst writing a ${stdHint} test case from a single requirement.`,
          `Reply strictly in ${langName(lang)}.`,
          `Return ONLY valid JSON: {"code": "${codePrefix}", "clause": string (short ref e.g. "REQ-4.4"), "steps": string (numbered concrete steps), "criteria": string (verifiable pass/fail criterion)}`,
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: String(requirement).slice(0, 800) }],
          maxTokens: 400,
          jsonMode: true,
        });
        sendJson(res, 200, extractJson(raw));
        return;
      }

      /* 09 — LIVE CODE / SQL SECURITY AUDIT */
      if (urlPath === '/api/audit') {
        const { code = '', lang = 'ru' } = body;
        const system = [
          'You are a senior AppSec & Postgres/React engineer auditing a code or SQL snippet (often generated by Lovable/Bolt/Cursor).',
          `Write findings and fixes concisely in ${langName(lang)}.`,
          'Return ONLY valid JSON: {"findings": [{"sev": "CRITICAL"|"HIGH"|"MEDIUM"|"LOW", "issue": string, "fix": string}]} (2 to 5 concrete findings).',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: String(code).slice(0, 4000) }],
          maxTokens: 700,
          jsonMode: true,
        });
        sendJson(res, 200, extractJson(raw));
        return;
      }

      sendJson(res, 404, { error: 'Unknown API endpoint' });
    } catch (err) {
      sendJson(res, 502, { error: err.message || 'Upstream LLM error' });
    }
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Portfolio server listening on http://0.0.0.0:${PORT} (LLM: ${LLM_ENABLED ? `${LLM_PROVIDER}/${LLM_MODEL}` : 'local-only'}, Vision: ${VISION_ENABLED ? LLM_VISION_MODEL : 'off'})`);
});
