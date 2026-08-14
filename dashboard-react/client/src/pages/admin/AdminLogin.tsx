// Style reminder: mirror the existing dark mesh/glass login card with orange action and restrained motion.

import { LockKeyhole, Loader2, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import { useLocation } from "wouter";
import { useAdmin } from "@/contexts/AdminContext";

export default function AdminLogin() {
  const [, navigate] = useLocation();
  const { login } = useAdmin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("Please enter both username and password.");
      return;
    }
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate("/admin");
    } catch {
      setError("Invalid username or password.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#0D1117] px-4 py-10 text-white"><img src="/images/kelembingo-login-texture.webp" alt="" className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-40" /><div className="relative w-full max-w-md rounded-[2rem] border border-white/[0.07] bg-[#1A1A2E]/85 p-8 shadow-[0_25px_60px_rgba(0,0,0,0.5)] backdrop-blur-xl"><div className="flex justify-center"><img src="/images/kelembingo-mark.webp" alt="Kelem Bingo mark" className="h-20 w-20 rounded-full object-contain drop-shadow-[0_8px_28px_rgba(249,115,22,0.35)]" /></div><div className="mt-5 text-center"><h1 className="text-2xl font-black tracking-tight">Kelem Bingo</h1><p className="mt-1.5 text-sm font-medium text-slate-400">Admin Dashboard</p></div><form onSubmit={submit} className="mt-8 space-y-5"><Field icon={<UserRound />} label="Username"><input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" placeholder="Enter your username" className="admin-field" /></Field><Field icon={<LockKeyhole />} label="Password"><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="Enter your password" className="admin-field" /></Field>{error && <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300" role="alert">{error}</div>}<button disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[#F97316] to-[#EA580C] py-3.5 text-sm font-black text-white shadow-[0_8px_22px_rgba(249,115,22,0.25)] transition-transform active:scale-[0.98] disabled:opacity-60">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? "Signing in…" : "Sign in"}</button></form><p className="mt-8 text-center text-xs font-semibold text-slate-600">@kelembingobot</p></div></main>;
}

function Field({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return <label className="block text-xs font-bold uppercase tracking-[0.16em] text-slate-400"><span className="mb-2 flex items-center gap-2">{icon}{label}</span>{children}</label>;
}
