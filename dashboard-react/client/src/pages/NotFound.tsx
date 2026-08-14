// Style reminder: keep fallback states quiet, dark, and easy to escape back to the player shell.

import { Link } from "wouter";
export default function NotFound() { return <div className="px-4 py-20 text-center"><p className="text-4xl font-black text-[#FF8C00]">404</p><h1 className="mt-3 text-xl font-black">Page not found</h1><p className="mt-2 text-xs text-white/40">Use the player navigation to return to a safe screen.</p><Link href="/" className="mt-6 inline-flex rounded-xl bg-[#FF8C00] px-4 py-3 text-xs font-black text-white">Back home</Link></div>; }
