// Style reminder: replicate legacy wallet.html and withdraw-modal.html: Wallet title, centered balance glass card, green/red action cards, recent transactions, and centered dark-glass modals.

import { ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePlayer } from "@/contexts/PlayerContext";
import { playerApi, type Transaction } from "@/lib/gateway";
import { etb, relativeDate, walletValue } from "@/lib/format";

export default function Wallet() {
  const { player, refresh } = usePlayer();
  const balance = walletValue(player?.play_wallet);
  const [modal, setModal] = useState<"deposit" | "withdraw" | null>(null);
  const [step, setStep] = useState(1);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [transactionsLoading, setTransactionsLoading] = useState(true);
  const [depositConfig, setDepositConfig] = useState<{ phone?: string; pending_count?: number; pending_limit?: number; ok?: boolean; error?: string }>({});
  const [deposit, setDeposit] = useState({ name: "", amount: "", transactionId: "" });
  const [withdraw, setWithdraw] = useState({ phone: "", name: "", amount: "" });
  const cacheAt = useRef(0);

  const loadTransactions = useCallback(async () => {
    const id = player?.user_id;
    if (!id || Date.now() - cacheAt.current < 15000) return;
    setTransactionsLoading(true);
    try {
      const [deposits, withdrawals] = await Promise.all([playerApi.deposits(id), playerApi.withdrawals(id)]);
      const all = [...deposits.map((item) => ({ ...item, type: "deposit" })), ...withdrawals.map((item) => ({ ...item, type: "withdraw" }))].sort((a, b) => new Date(String(b.created_at || (b as Transaction & { createdAt?: string }).createdAt || 0)).getTime() - new Date(String(a.created_at || (a as Transaction & { createdAt?: string }).createdAt || 0)).getTime());
      setTransactions(all.slice(0, 8));
      cacheAt.current = Date.now();
    } catch {
      setTransactions([]);
    } finally { setTransactionsLoading(false); }
  }, [player?.user_id]);

  useEffect(() => { void loadTransactions(); }, [loadTransactions]);

  async function openDeposit() {
    if (!player?.user_id) { setNotice("Open KelemBingo from Telegram to use your wallet."); return; }
    setBusy(true); setNotice("");
    try {
      const config = await playerApi.depositConfig(player.user_id);
      setDepositConfig(config);
      if (!config.ok) { setNotice(config.error === "too_many_pending" ? "You already have too many pending deposits." : config.error === "admin_offline" ? "Admin is offline. Please try again later." : "Deposit is not available right now."); return; }
      setDeposit((old) => ({ ...old, name: player.first_name || "" })); setStep(1); setModal("deposit");
    } catch (e) { setNotice(e instanceof Error ? e.message : "Could not load deposit settings"); } finally { setBusy(false); }
  }

  async function submitDeposit() {
    const name = deposit.name.trim(); const amount = Number(deposit.amount); const transactionId = deposit.transactionId.trim();
    if (!name || !amount || amount < 10 || transactionId.length < 3) { setNotice("Enter a TeleBirr name, a deposit of at least 10 ETB, and a valid transaction number."); return; }
    setBusy(true);
    try { await playerApi.submitDeposit({ telebirr_name: name, amount, transaction_id: transactionId }); setNotice("Deposit request submitted."); setModal(null); cacheAt.current = 0; await Promise.all([refresh(), loadTransactions()]); } catch (e) { setNotice(e instanceof Error ? e.message : "Could not submit deposit"); } finally { setBusy(false); }
  }

  async function submitWithdrawal() {
    const amount = Number(withdraw.amount); const phone = withdraw.phone.trim(); const name = withdraw.name.trim();
    if (!amount || amount < 50 || !phone || !name) { setNotice("Minimum withdrawal is 50 ETB. Enter phone and TeleBirr full name."); return; }
    setBusy(true); const key = `withdrawal:${crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;
    try { const response = await playerApi.createWithdrawal({ amount, phone, telebirr_name: name }, key); if (response.error) { const messages: Record<string, string> = { below_min: `Minimum withdrawal: ${response.min || 50} ETB.`, insufficient: "Insufficient balance.", pending_exists: "You already have a pending withdrawal.", system_error: "Server error validating withdrawal. Try again." }; throw new Error(messages[response.error] || response.error); } setNotice("Withdrawal request submitted."); setModal(null); cacheAt.current = 0; await Promise.all([refresh(), loadTransactions()]); } catch (e) { setNotice(e instanceof Error ? e.message : "Could not submit withdrawal"); } finally { setBusy(false); }
  }

  return <div className="min-h-[calc(100vh-56px)] bg-[linear-gradient(180deg,#0D1117_0%,#0A1628_40%,#111827_100%)] px-4 py-4"><h2 className="mb-4 text-xl font-bold text-white">Wallet</h2><div className="glass mb-4 rounded-2xl border border-white/10 bg-[#1A1A2E]/75 p-5 text-center"><div className="mb-1 text-xs uppercase text-white/50">Wallet Balance</div><div className="text-4xl font-black text-[#10B981]">{balance.toLocaleString()} ETB</div></div><div className="mb-6 grid grid-cols-2 gap-3"><button onClick={() => void openDeposit()} disabled={busy} className="rounded-xl bg-gradient-to-br from-[#10B981] to-[#059669] p-4 text-center shadow-[0_8px_25px_rgba(16,185,129,0.25)] transition-transform active:scale-[0.97] disabled:opacity-50"><div className="mb-1 text-lg">💳</div><div className="text-sm font-semibold text-white">Deposit</div></button><button onClick={() => { setWithdraw({ phone: player?.phone || "", name: player?.first_name || "", amount: "" }); setModal("withdraw"); }} disabled={busy} className="rounded-xl bg-gradient-to-br from-[#EF4444] to-[#F97316] p-4 text-center shadow-[0_8px_25px_rgba(239,68,68,0.22)] transition-transform active:scale-[0.97] disabled:opacity-50"><div className="mb-1 text-lg">💸</div><div className="text-sm font-semibold text-white">Withdraw</div></button></div>{notice && <div className="mb-4 flex items-start gap-2 rounded-xl border border-[#F59E0B]/20 bg-[#F59E0B]/10 px-3 py-2 text-xs text-[#FCD34D]" role="status"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}<h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/70">Recent Transactions</h3>{transactionsLoading ? <div className="glass rounded-xl border border-white/10 bg-[#1A1A2E]/70 p-4 text-center"><Loader2 className="mx-auto h-4 w-4 animate-spin text-white/30" /></div> : transactions.length ? <div className="space-y-2">{transactions.map((item, index) => <div key={item.id || index} className="flex items-center justify-between rounded-xl border border-white/10 bg-[#1A1A2E]/70 px-4 py-3"><div><p className="text-xs font-black capitalize">{item.type || "transaction"}</p><p className="mt-1 text-[10px] uppercase text-white/35">{item.status || "pending"} · {relativeDate(item.created_at)}</p></div><p className={`text-sm font-black ${item.type === "withdraw" ? "text-[#FFB45C]" : "text-[#34D399]"}`}>{item.type === "withdraw" ? "−" : "+"}{etb(item.amount)}</p></div>)}</div> : <div className="glass rounded-xl border border-white/10 bg-[#1A1A2E]/70 p-4 text-center"><p className="text-sm text-white/30">No transactions yet</p></div>}{modal === "deposit" && <DepositModal step={step} setStep={setStep} values={deposit} setValues={setDeposit} config={depositConfig} busy={busy} onClose={() => setModal(null)} onSubmit={() => void submitDeposit()} />}{modal === "withdraw" && <WithdrawModal values={withdraw} setValues={setWithdraw} busy={busy} balance={balance} onClose={() => setModal(null)} onSubmit={() => void submitWithdrawal()} />}</div>;
}

function DepositModal({ step, setStep, values, setValues, config, busy, onClose, onSubmit }: { step: number; setStep: (step: number) => void; values: { name: string; amount: string; transactionId: string }; setValues: (value: { name: string; amount: string; transactionId: string }) => void; config: { phone?: string; pending_count?: number; pending_limit?: number }; busy: boolean; onClose: () => void; onSubmit: () => void }) { return <Modal title="Deposit Funds" subtitle="Follow the same TeleBirr deposit flow from the bot." onClose={onClose}>{step === 1 ? <><div className="glass rounded-xl border border-white/10 bg-white/[0.03] p-3 text-center"><div className="text-xs text-white/50">Pending Deposit Requests</div><div className="text-xl font-bold text-[#10B981]">{config.pending_count || 0} / {config.pending_limit || 3}</div></div><Field label="TeleBirr Full Name"><input type="text" value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} placeholder="Name on TeleBirr account" autoComplete="name" className="field focus:border-[#10B981]" /></Field><Field label="Amount (ETB)"><input type="number" min="10" value={values.amount} onChange={(e) => setValues({ ...values, amount: e.target.value })} placeholder="Enter amount" className="field focus:border-[#10B981]" /></Field><div className="flex gap-3 pt-1"><button onClick={onClose} className="secondary">Cancel</button><button onClick={() => { if (values.name.trim() && Number(values.amount) >= 10) setStep(2); }} className="primary-green">Next</button></div></> : <><div className="glass rounded-xl border border-[#14B8A6]/25 bg-white/[0.03] p-4"><div className="text-xs uppercase text-white/50">TeleBirr Number</div><div className="text-lg font-bold text-[#14B8A6]">{config.phone || "—"}</div><p className="mt-2 text-xs text-white/45">Send the money first, then enter the transaction number from your receipt.</p></div><Field label="Transaction Number"><input value={values.transactionId} onChange={(e) => setValues({ ...values, transactionId: e.target.value })} placeholder="Enter receipt transaction number" className="field focus:border-[#10B981]" /></Field><div className="flex gap-3 pt-1"><button onClick={() => setStep(1)} className="secondary">Back</button><button onClick={onSubmit} disabled={busy} className="primary-green">{busy ? "Submitting…" : "Submit"}</button></div></>}</Modal>; }
function WithdrawModal({ values, setValues, busy, balance, onClose, onSubmit }: { values: { phone: string; name: string; amount: string }; setValues: (value: { phone: string; name: string; amount: string }) => void; busy: boolean; balance: number; onClose: () => void; onSubmit: () => void }) { return <Modal title="Withdraw Funds" onClose={onClose}><div className="glass mb-4 rounded-xl border border-white/10 bg-white/[0.03] p-3 text-center"><div className="text-xs text-white/50">Available Balance</div><div className="text-xl font-bold text-[#10B981]">{etb(balance)}</div></div><div className="space-y-3"><Field label="Amount (ETB)"><input type="number" min="50" max={balance} value={values.amount} onChange={(e) => setValues({ ...values, amount: e.target.value })} placeholder="Enter amount" className="field focus:border-[#FF8C00]" /></Field><Field label="TeleBirr Phone Number"><input type="tel" value={values.phone} onChange={(e) => setValues({ ...values, phone: e.target.value })} placeholder="+251911000000" inputMode="tel" autoComplete="tel" className="field focus:border-[#FF8C00]" /></Field><Field label="TeleBirr Full Name"><input type="text" value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} placeholder="Name on TeleBirr account" autoComplete="name" className="field focus:border-[#FF8C00]" /></Field><div className="flex gap-3"><button onClick={onClose} className="secondary">Cancel</button><button onClick={onSubmit} disabled={busy} className="primary-danger">{busy ? "Submitting…" : "Submit"}</button></div></div></Modal>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="mt-3 block text-xs uppercase text-white/50">{label}{children}</label>; }
function Modal({ title, subtitle, children, onClose }: { title: string; subtitle?: string; children: React.ReactNode; onClose: () => void }) { return <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"><div className="absolute inset-x-4 top-[18%] mx-auto max-w-[380px]"><div className="glass rounded-2xl border border-white/10 bg-[#1A1A2E]/90 p-5 shadow-2xl"><div className="mb-4 flex items-center justify-between"><div><h3 className="text-lg font-bold text-white">{title}</h3>{subtitle && <p className="mt-1 text-xs text-white/45">{subtitle}</p>}</div><button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-white/70" aria-label="Close"><X className="h-4 w-4" /></button></div>{children}</div></div></div>; }
