// Style reminder: placeholders are temporary migration checkpoints, not fake gameplay; unavailable actions are explicit.

import { Construction } from "lucide-react";
export default function Placeholder({ title, detail }: { title: string; detail: string }) { return <div className="px-4 py-16 text-center"><Construction className="mx-auto h-8 w-8 text-[#FF8C00]" /><h1 className="mt-4 text-xl font-black">{title}</h1><p className="mx-auto mt-2 max-w-[280px] text-xs leading-relaxed text-white/40">{detail}</p></div>; }
