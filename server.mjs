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
        : 'gpt-4o-mini');

const LLM_ENABLED = LLM_PROVIDER === 'ollama' || Boolean(LLM_API_KEY);

// Simple in-memory rate limiter per IP so public demo tunnels stay safe
const hits = new Map();
const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_MAX = Number(process.env.RATE_LIMIT_MAX || 40);

function checkRateLimit(ip) {
  const now = Date.now();
  const list = (hits.get(ip) || []).filter((ts) => now - ts < RATE_WINDOW_MS);
  if (list.length >= RATE_MAX) return false;
  list.push(now);
  hits.set(ip, list);
  return true;
}

function readJsonBody(req, maxBytes = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > maxBytes) {
        req.destroy();
        reject(new Error('Payload too large'));
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

function extractJsonObject(text) {
  const cleaned = String(text || '')
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start === -1 || end === -1 || end <= start) {
    throw new Error('Model did not return JSON');
  }
  return JSON.parse(cleaned.slice(start, end + 1));
}

async function callLLM({ system, messages, maxTokens = 550, jsonMode = false }) {
  if (!LLM_ENABLED) throw new Error('LLM not configured');

  if (LLM_PROVIDER === 'anthropic') {
    const res = await fetch(`${LLM_BASE_URL}/v1/messages`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': LLM_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: LLM_MODEL,
        max_tokens: maxTokens,
        temperature: 0.2,
        system,
        messages: messages.map((m) => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: String(m.content || ''),
        })),
      }),
    });
    if (!res.ok) throw new Error(`Anthropic HTTP ${res.status}`);
    const data = await res.json();
    return data.content?.[0]?.text || '';
  }

  if (LLM_PROVIDER === 'gemini') {
    const url = `${LLM_BASE_URL}/v1beta/models/${encodeURIComponent(LLM_MODEL)}:generateContent?key=${encodeURIComponent(LLM_API_KEY)}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: messages.map((m) => ({
          role: m.role === 'assistant' ? 'model' : 'user',
          parts: [{ text: String(m.content || '') }],
        })),
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

  // OpenAI-compatible (OpenAI, OpenRouter, DeepSeek, Groq, Ollama)
  const headers = { 'content-type': 'application/json' };
  if (LLM_API_KEY) headers.authorization = `Bearer ${LLM_API_KEY}`;

  const res = await fetch(`${LLM_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model: LLM_MODEL,
      temperature: 0.2,
      max_tokens: maxTokens,
      ...(jsonMode && LLM_BASE_URL.includes('api.openai.com') ? { response_format: { type: 'json_object' } } : {}),
      messages: [{ role: 'system', content: system }, ...messages],
    }),
  });
  if (!res.ok) throw new Error(`LLM HTTP ${res.status}`);
  const data = await res.json();
  return data.choices?.[0]?.message?.content || '';
}

const server = http.createServer(async (req, res) => {
  const urlPath = (req.url || '/').split('?')[0];

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
      provider: LLM_ENABLED ? LLM_PROVIDER : 'local',
      model: LLM_ENABLED ? LLM_MODEL : 'deterministic',
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

      if (urlPath === '/api/chat') {
        const { messages = [], kb = {}, bookedSlots = [], lang = 'ru' } = body;
        const system = [
          'You are the front-desk AI assistant for a dental clinic in a live portfolio demo.',
          'All human operators are currently busy, so you handle incoming inquiries.',
          `Reply in the customer's language (default UI language: ${lang}), concise and natural (max 3 sentences).`,
          'STRICT RULES:',
          '- Use ONLY facts from the Knowledge Base JSON below. Never invent prices, doctors, discounts, or policies.',
          `- Already booked slots (UNAVAILABLE, do not offer these): ${JSON.stringify(bookedSlots)}.`,
          '- If the user asks about insurance (ДМС / mutuelle), installment plans, sedation/narcosis, or anything not in the KB, DO NOT guess: explain briefly and set action.type = "handoff".',
          '- To book a slot, you need service, an available slot, client name, and phone number. Once all four are present, confirm the booking and set action.type = "lead".',
          `Knowledge Base JSON:\n${JSON.stringify(kb)}`,
          'Return ONLY valid JSON: {"reply": string, "action": {"type": "none"|"lead"|"handoff", "name"?: string, "phone"?: string, "service"?: string, "slot"?: string, "reason"?: string}}',
        ].join('\n');

        const raw = await callLLM({
          system,
          messages: messages.slice(-10),
          maxTokens: 400,
          jsonMode: true,
        });
        const parsed = extractJsonObject(raw);
        sendJson(res, 200, parsed);
        return;
      }

      if (urlPath === '/api/rag') {
        const { query = '', chunks = [], role = 'staff' } = body;
        if (!chunks.length) {
          sendJson(res, 200, { answer: null });
          return;
        }
        const ctx = chunks.map((c) => `[${c.id}] (${c.src}) ${c.text}`).join('\n');
        const system = [
          `You are a corporate knowledge-base assistant. Current user role: ${role}.`,
          'Answer the question in its own language in 1-3 concise sentences using ONLY the retrieved fragments below.',
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

      if (urlPath === '/api/listing') {
        const { note = '' } = body;
        const system = [
          'Convert the seller warehouse note into an eBay UK/US listing.',
          'Use ONLY facts present in the note. Never invent specs or warranties.',
          'Return ONLY valid JSON:',
          '{"title": string (<=80 chars, keyword-first, no ALL CAPS, no !!!), "category": string, "conditionEnum": "NEW"|"USED_GOOD", "specifics": object, "paragraphs": string[] (3-4 honest plain-text paragraphs)}',
        ].join('\n');
        const raw = await callLLM({
          system,
          messages: [{ role: 'user', content: String(note).slice(0, 1500) }],
          maxTokens: 500,
          jsonMode: true,
        });
        const parsed = extractJsonObject(raw);
        sendJson(res, 200, parsed);
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
  console.log(`Portfolio server listening on http://0.0.0.0:${PORT} (LLM: ${LLM_ENABLED ? `${LLM_PROVIDER}/${LLM_MODEL}` : 'local-only'})`);
});
