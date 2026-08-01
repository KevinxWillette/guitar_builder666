/* Guitarmory storage adapter.
 *
 * DEMO MODE (current): builds and votes live in this browser's
 * localStorage — perfect for trying the flow, but votes are not shared
 * between visitors.
 *
 * TO GO LIVE: create a free Supabase project, make a `builds` table
 * (id uuid pk default gen_random_uuid(), name text, image text,
 *  votes int default 0, week text, created_at timestamptz default now())
 * with row-level security allowing anon select/insert and an RPC
 * `vote_build(build_id uuid)` that increments votes. Then set
 * SUPABASE_URL and SUPABASE_ANON_KEY below — the adapter switches over
 * automatically.
 */
"use strict";

const SUPABASE_URL = "";      // e.g. "https://xyzcompany.supabase.co"
const SUPABASE_ANON_KEY = ""; // the anon public key

function weekStamp(d = new Date()) {
  // ISO week id like 2026-W32 — the voting period
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date - yearStart) / 86400000 + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

const LocalStore = {
  mode: "demo",
  _read() {
    try { return JSON.parse(localStorage.getItem("guitarmory") || "[]"); }
    catch { return []; }
  },
  _write(builds) { localStorage.setItem("guitarmory", JSON.stringify(builds)); },
  async submit(name, imageDataUrl) {
    const builds = this._read();
    builds.push({
      id: crypto.randomUUID(), name: (name || "Unnamed Killette").slice(0, 40),
      image: imageDataUrl, votes: 0, week: weekStamp(),
      created_at: new Date().toISOString(),
    });
    this._write(builds);
  },
  async list(week) {
    return this._read()
      .filter(b => !week || b.week === week)
      .sort((a, b) => b.votes - a.votes);
  },
  async vote(id) {
    const key = "guitarmory_voted";
    const voted = JSON.parse(localStorage.getItem(key) || "[]");
    if (voted.includes(id)) return false;
    const builds = this._read();
    const b = builds.find(x => x.id === id);
    if (!b) return false;
    b.votes += 1;
    this._write(builds);
    voted.push(id);
    localStorage.setItem(key, JSON.stringify(voted));
    return true;
  },
  async champion() {
    // last completed week's top build, falling back to this week's leader
    const builds = this._read();
    const now = weekStamp();
    const past = builds.filter(b => b.week !== now).sort((a, b) => b.votes - a.votes);
    if (past.length && past[0].votes > 0) return past[0];
    const current = builds.filter(b => b.week === now).sort((a, b) => b.votes - a.votes);
    return current.length && current[0].votes > 0 ? current[0] : null;
  },
};

const SupabaseStore = {
  mode: "live",
  async _req(path, opts = {}) {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
      ...opts,
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
        ...(opts.headers || {}),
      },
    });
    if (!res.ok) throw new Error(`store ${res.status}`);
    return res.status === 204 ? null : res.json();
  },
  async submit(name, imageDataUrl) {
    await this._req("builds", {
      method: "POST",
      body: JSON.stringify({
        name: (name || "Unnamed Killette").slice(0, 40),
        image: imageDataUrl, week: weekStamp(),
      }),
    });
  },
  async list(week) {
    const q = week ? `builds?week=eq.${week}&order=votes.desc` : "builds?order=votes.desc";
    return this._req(q);
  },
  async vote(id) {
    const key = "guitarmory_voted";
    const voted = JSON.parse(localStorage.getItem(key) || "[]");
    if (voted.includes(id)) return false;
    await fetch(`${SUPABASE_URL}/rest/v1/rpc/vote_build`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ build_id: id }),
    });
    voted.push(id);
    localStorage.setItem(key, JSON.stringify(voted));
    return true;
  },
  async champion() {
    const rows = await this._req("builds?order=votes.desc&limit=50");
    const now = weekStamp();
    const past = rows.filter(b => b.week !== now);
    if (past.length && past[0].votes > 0) return past[0];
    const cur = rows.filter(b => b.week === now);
    return cur.length && cur[0].votes > 0 ? cur[0] : null;
  },
};

window.ArmoryStore = (SUPABASE_URL && SUPABASE_ANON_KEY) ? SupabaseStore : LocalStore;
window.armoryWeek = weekStamp;
