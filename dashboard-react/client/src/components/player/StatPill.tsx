// Style reminder: metrics use compact glass pills and semantic accent colors matching the legacy player UI.

export default function StatPill({ label, value, tone }: { label: string; value: React.ReactNode; tone: "orange" | "green" | "blue" | "purple" | "teal" }) {
  const tones = { orange: "border-[#FF8C00]/30 bg-[#FF8C00]/10 text-[#FF8C00]", green: "border-[#10B981]/30 bg-[#10B981]/10 text-[#34D399]", blue: "border-[#3B82F6]/30 bg-[#3B82F6]/10 text-[#60A5FA]", purple: "border-[#A855F7]/30 bg-[#A855F7]/10 text-[#C084FC]", teal: "border-[#14B8A6]/30 bg-[#14B8A6]/10 text-[#2DD4BF]" } as const;
  return <div className={`rounded-xl border px-3 py-2 ${tones[tone]}`}><p className="text-[9px] font-semibold uppercase tracking-[0.16em] opacity-60">{label}</p><p className="mt-1 text-sm font-black leading-none">{value}</p></div>;
}
