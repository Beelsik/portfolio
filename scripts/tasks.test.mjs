import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { encodeTaskZ, decodeTaskZ } from './make-task.mjs';
import { summarizeVisitsText } from './analyze-visits.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const TASKS_DIR = path.join(ROOT, 'tasks');

const ALLOWED_LANGS = new Set(['ru', 'uk', 'en', 'fr']);
const ALLOWED_KINDS = new Set(['io', 'code', 'ai', 'db', 'human']);
const ALLOWED_CASES = new Set(['project', 'sales', 'rag', 'docs', 'parser', 'listing', 'hand', 'cc', 'gost', 'spec', 'audit', 'redteam']);

test('all tasks/*.json files pass schema, length, pilot wording, and UK isolation checks', () => {
  const files = fs.readdirSync(TASKS_DIR).filter((f) => f.endsWith('.json'));
  assert.ok(files.length >= 4, 'Expected at least 4 pre-generated task files');

  for (const file of files) {
    const stem = file.replace(/\.json$/i, '');
    const raw = fs.readFileSync(path.join(TASKS_DIR, file), 'utf8');
    const t = JSON.parse(raw);

    assert.equal(t.slug, stem, `${file}: slug must match filename`);
    assert.match(t.slug, /^[a-z0-9][a-z0-9_-]{0,63}$/i, `${file}: valid slug`);
    assert.ok(ALLOWED_LANGS.has(t.lang), `${file}: invalid lang ${t.lang}`);

    for (const k of ['title', 'brief', 'summary', 'monthlyOps']) {
      assert.equal(typeof t[k], 'string', `${file}: ${k} must be string`);
      assert.ok(t[k].trim().length > 10, `${file}: ${k} must be non-empty`);
    }

    assert.ok(Array.isArray(t.nodes) && t.nodes.length >= 4 && t.nodes.length <= 6, `${file}: 4..6 nodes`);
    for (const n of t.nodes) {
      assert.ok(ALLOWED_KINDS.has(n.kind), `${file}: invalid node kind ${n.kind}`);
      assert.ok(n.title.length >= 2 && n.title.length <= 19, `${file}: node.title "${n.title}" length (${n.title.length}) > 19`);
      assert.ok(n.tech.length >= 2 && n.tech.length <= 22, `${file}: node.tech "${n.tech}" length (${n.tech.length}) > 22`);
    }

    assert.ok(Array.isArray(t.split?.code) && t.split.code.length >= 2, `${file}: split.code >= 2`);
    assert.ok(Array.isArray(t.split?.ai) && t.split.ai.length >= 1, `${file}: split.ai >= 1`);

    assert.ok(Array.isArray(t.milestones) && t.milestones.length === 3, `${file}: exactly 3 milestones`);
    const p1Text = `${t.milestones[0].phase} ${t.milestones[0].deliverable} ${t.milestones[0].estimate}`;
    assert.doesNotMatch(p1Text, /(бесплатн|безкоштовн|\bfree\b|gratuit)/i, `${file}: phase 1 must not say free`);

    assert.ok(Array.isArray(t.questions) && t.questions.length === 3, `${file}: exactly 3 questions`);
    assert.ok(ALLOWED_CASES.has(t.relatedCase), `${file}: invalid relatedCase ${t.relatedCase}`);

    if (t.lang === 'uk') {
      assert.doesNotMatch(raw, /[ыэъёЫЭЪЁ₽]/, `${file}: UK task must contain zero Russian characters`);
    }
  }
});

test('deflate-raw z: task round-trip preserves exact JSON payload', () => {
  const sample = JSON.parse(fs.readFileSync(path.join(TASKS_DIR, 'bitrix-invoices.json'), 'utf8'));
  const encoded = encodeTaskZ(sample);
  assert.ok(encoded.startsWith('z:'));
  assert.ok(encoded.length < 4000, 'Expected compact URL-friendly payload');
  const decoded = decodeTaskZ(encoded);
  assert.deepEqual(decoded, sample);
});

test('portfolio.html and index.html are identical and ua.html has zero RU leaks', () => {
  const pf = fs.readFileSync(path.join(ROOT, 'portfolio.html'));
  const idx = fs.readFileSync(path.join(ROOT, 'index.html'));
  assert.equal(Buffer.compare(pf, idx), 0, 'portfolio.html and index.html must be byte-for-byte equal');

  const ua = fs.readFileSync(path.join(ROOT, 'ua.html'), 'utf8');
  assert.doesNotMatch(ua, /[ыэъёЫЭЪЁ₽]|ru-RU/, 'ua.html must have zero Russian characters or ru-RU locale');
});

test('both index.html and ua.html expose 3 fixed-price starter packages in #packages', () => {
  for (const fname of ['index.html', 'ua.html']) {
    const html = fs.readFileSync(path.join(ROOT, fname), 'utf8');
    assert.match(html, /id="packages"/, `${fname}: missing #packages section`);
    const secMatch = html.match(/id="packages"[\s\S]*?<table class="ch-spec pkg-table">[\s\S]*?<tbody>([\s\S]*?)<\/tbody>/);
    assert.ok(secMatch, `${fname}: missing .pkg-table tbody inside #packages`);
    const tbody = secMatch[1];
    const rows = tbody.match(/<tr\b/g) || [];
    const amts = tbody.match(/class="pkg-amt"/g) || [];
    const days = tbody.match(/class="pkg-days"/g) || [];
    assert.equal(rows.length, 3, `${fname}: expected 3 starter package rows`);
    assert.equal(amts.length, 3, `${fname}: expected 3 .pkg-amt prices`);
    assert.equal(days.length, 3, `${fname}: expected 3 .pkg-days timelines`);
  }
});

test('server.mjs serves /tasks/*.json with ETag/304, blocks traversal, tracks ?src=/api/event & protects /api/stats', async () => {
  const tmpVisits = path.join(os.tmpdir(), `pf-visits-test-${Date.now()}.jsonl`);
  let serverStdout = '';
  const proc = spawn(process.execPath, [path.join(ROOT, 'server.mjs')], {
    cwd: ROOT,
    env: { ...process.env, PORT: '0', DISABLE_KEEPALIVE: '1', STATS_KEY: 'test-secret-123', VISITS_LOG_PATH: tmpVisits },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out waiting for server port')), 8000);
      let resolved = false;
      proc.stdout.on('data', (chunk) => {
        serverStdout += chunk.toString('utf8');
        if (!resolved) {
          const m = serverStdout.match(/http:\/\/0\.0\.0\.0:(\d+)/);
          if (m) {
            resolved = true;
            clearTimeout(timer);
            resolve(Number(m[1]));
          }
        }
      });
      proc.stderr.on('data', (chunk) => {
        serverStdout += chunk.toString('utf8');
      });
      proc.on('exit', (code) => {
        if (!resolved) {
          clearTimeout(timer);
          reject(new Error(`Server exited early (${code}): ${serverStdout}`));
        }
      });
    });

    const base = `http://127.0.0.1:${port}`;

    const r1 = await fetch(`${base}/tasks/bitrix-invoices.json`);
    assert.equal(r1.status, 200);
    const etag = r1.headers.get('etag');
    assert.ok(etag, 'ETag header must be set on task JSON');
    const json = await r1.json();
    assert.equal(json.slug, 'bitrix-invoices');

    const r304 = await fetch(`${base}/tasks/bitrix-invoices.json`, { headers: { 'If-None-Match': etag } });
    assert.equal(r304.status, 304);

    const rTrav = await fetch(`${base}/tasks/..%2F.env.json`);
    assert.ok(rTrav.status === 400 || rTrav.status === 404, `Expected 400/404 for traversal, got ${rTrav.status}`);

    const rBad = await fetch(`${base}/tasks/bad!slug.json`);
    assert.equal(rBad.status, 400);

    const rMiss = await fetch(`${base}/tasks/nonexistent-task-999.json`);
    assert.equal(rMiss.status, 404);

    const rCors = await fetch(`${base}/api/health`, {
      method: 'OPTIONS',
      headers: { Origin: 'https://beelsik.github.io' },
    });
    assert.equal(rCors.status, 204);
    assert.equal(rCors.headers.get('access-control-allow-origin'), 'https://beelsik.github.io');

    const rGetSrc = await fetch(`${base}/?src=kwork&task=bitrix-invoices`, {
      headers: { 'User-Agent': 'Mozilla/5.0 Test' },
    });
    assert.equal(rGetSrc.status, 200);

    const rEvent = await fetch(`${base}/api/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=UTF-8', 'User-Agent': 'Mozilla/5.0 Test' },
      body: JSON.stringify({
        src: 'kwork',
        task: 'bitrix-invoices',
        page: '/',
        lang: 'ru',
        dev: 'desktop',
        sid: 'ab12cd34',
        event: 'view',
        stands: ['architect', 'packages', 'sales'],
      }),
    });
    assert.equal(rEvent.status, 204);

    const rNoKey = await fetch(`${base}/api/stats`);
    assert.equal(rNoKey.status, 404);

    const rStats = await fetch(`${base}/api/stats?key=test-secret-123`);
    assert.equal(rStats.status, 200);
    const statsJson = await rStats.json();
    assert.equal(statsJson.bySource?.kwork?.sessions, 1);
    assert.ok(statsJson.bySource?.kwork?.hits >= 1);
    assert.equal(statsJson.byStand?.packages?.views, 1);
    assert.match(serverStdout, /\[visit\].*src=kwork.*event=view.*stands=architect,packages,sales/);
  } finally {
    proc.kill('SIGTERM');
    try { fs.unlinkSync(tmpVisits); } catch {}
  }
});

test('analyze-visits.mjs summarizes Render [visit] log lines accurately', () => {
  const sample = [
    '2026-11-21T03:40:00Z [visit] 2026-11-21T03:40:00.000Z | src=kwork | task=bitrix-invoices | page=/ | lang=ru | dev=desktop | sid=ab12cd34 | event=open | stands=architect',
    '[visit] 2026-11-21T03:40:05.000Z | src=kwork | task=bitrix-invoices | page=/ | lang=ru | dev=desktop | sid=ab12cd34 | event=view | stands=architect,packages,project',
    '[visit] 2026-11-21T03:41:00.000Z | src=codeur | task=- | page=/ | lang=fr | dev=mobile | sid=ef56gh78 | event=act | stands=audit:aud-run-btn',
  ].join('\n');
  const out = summarizeVisitsText(sample);
  assert.equal(out.totalEvents, 3);
  assert.equal(out.totalSessions, 2);
  assert.equal(out.bySource.kwork.sessions, 1);
  assert.equal(out.bySource.kwork.tasks['bitrix-invoices'], 2);
  assert.equal(out.byStand.packages.views, 1);
  assert.equal(out.byStand.audit.actions, 1);
});
