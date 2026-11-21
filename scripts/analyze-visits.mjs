#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

export function parseVisitLine(line) {
  const s = String(line || '').trim();
  if (!s) return null;
  if (s.startsWith('{')) {
    try {
      const j = JSON.parse(s);
      if (j && j.src && j.event) return j;
    } catch {}
  }
  const m = s.match(/\[visit\]\s+(.+)$/);
  if (!m) return null;
  const parts = m[1].split('|').map((x) => x.trim());
  const rec = { ts: parts[0] || '', stands: [] };
  for (const p of parts.slice(1)) {
    const eq = p.indexOf('=');
    if (eq <= 0) continue;
    const k = p.slice(0, eq).trim();
    const v = p.slice(eq + 1).trim();
    if (k === 'stands') {
      rec.stands = v && v !== '-' ? v.split(',').map((x) => x.trim()).filter(Boolean) : [];
    } else {
      rec[k] = v;
    }
  }
  return rec.src && rec.event ? rec : null;
}

export function summarizeVisitsText(rawText) {
  const bySource = {};
  const byStand = {};
  const totalSessions = new Set();
  let totalEvents = 0;

  for (const line of String(rawText || '').split(/\r?\n/)) {
    const rec = parseVisitLine(line);
    if (!rec) continue;
    totalEvents += 1;
    const src = rec.src || 'direct';
    if (!bySource[src]) {
      bySource[src] = { events: 0, hits: 0, sessions: new Set(), tasks: {}, views: {}, actions: {} };
    }
    const bucket = bySource[src];
    bucket.events += 1;
    if (rec.event === 'hit' || rec.event === 'open') bucket.hits += 1;
    if (rec.sid && rec.sid !== '-' && rec.sid !== 'http') {
      bucket.sessions.add(rec.sid);
      totalSessions.add(`${src}:${rec.sid}`);
    }
    if (rec.task && rec.task !== '-') {
      bucket.tasks[rec.task] = (bucket.tasks[rec.task] || 0) + 1;
    }
    for (const st of rec.stands || []) {
      const base = String(st).split(':')[0] || st;
      if (rec.event === 'view') {
        bucket.views[st] = (bucket.views[st] || 0) + 1;
        byStand[base] = byStand[base] || { views: 0, actions: 0 };
        byStand[base].views += 1;
      } else if (rec.event === 'act') {
        bucket.actions[st] = (bucket.actions[st] || 0) + 1;
        byStand[base] = byStand[base] || { views: 0, actions: 0 };
        byStand[base].actions += 1;
      }
    }
  }

  const sourcesOut = {};
  for (const [k, v] of Object.entries(bySource)) {
    sourcesOut[k] = {
      events: v.events,
      hits: v.hits,
      sessions: v.sessions.size,
      tasks: v.tasks,
      views: v.views,
      actions: v.actions,
    };
  }
  return { totalEvents, totalSessions: totalSessions.size, bySource: sourcesOut, byStand };
}

function topEntries(obj, limit = 5) {
  return Object.entries(obj || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([k, n]) => `${k}(${n})`)
    .join(', ') || '-';
}

function main() {
  const argPath = process.argv[2];
  const filePath = argPath ? path.resolve(argPath) : path.join(ROOT, 'visits.jsonl');
  let raw = '';
  if (argPath === '-' || (!argPath && !process.stdin.isTTY)) {
    raw = fs.readFileSync(0, 'utf8');
  } else if (fs.existsSync(filePath)) {
    raw = fs.readFileSync(filePath, 'utf8');
  } else {
    console.log(`No log file found at ${filePath}.`);
    console.log('Usage: node scripts/analyze-visits.mjs [visits.jsonl | render-logs.txt | -]');
    process.exit(0);
  }

  const summary = summarizeVisitsText(raw);
  console.log(`\nVisit Analytics: ${summary.totalSessions} session(s), ${summary.totalEvents} event(s)\n`);
  const srcList = Object.entries(summary.bySource).sort((a, b) => (b[1].sessions || b[1].hits) - (a[1].sessions || a[1].hits));
  for (const [src, info] of srcList) {
    console.log(`Source: ${src} | sessions=${info.sessions} | hits=${info.hits} | events=${info.events}`);
    console.log(`  Tasks:   ${topEntries(info.tasks)}`);
    console.log(`  Views:   ${topEntries(info.views, 8)}`);
    console.log(`  Actions: ${topEntries(info.actions, 8)}`);
  }
  console.log('\nBy Stand (all sources):');
  const standsSorted = Object.entries(summary.byStand).sort((a, b) => (b[1].views + b[1].actions) - (a[1].views + a[1].actions));
  for (const [st, c] of standsSorted) {
    console.log(`  ${st.padEnd(14)} views=${String(c.views).padEnd(4)} actions=${c.actions}`);
  }
  console.log('');
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  main();
}
