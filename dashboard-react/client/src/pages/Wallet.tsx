// Style reminder: match the legacy wallet flow with a compact dark-glass balance card, clear ETB actions, and accessible Telegram-sized dialogs.

import { ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { usePlayer } from "@/contexts/PlayerContext";
import { formatGatewayError, playerApi, type Transaction } from "@/lib/gateway";
import { etb, relativeDate, walletValue } from "@/lib/format";

type DepositValues = { name: string; amount: string; transactionId: string };
type WithdrawValues = { phone: string; name: string; amount: string };
type DepositConfig = { phone?: string; pending_count?: number; pending_limit?: number; ok?: boolean; error?: string };

const inputClass = "h-12 rounded-xl border-white/10 bg-white/[0.045] px-4 text-sm text-white shadow-inner placeholder:text-white/25 focus-visible:border-[#FF8C00] focus-visible:ring-2 focus-visible:ring-[#FF8C00]/25";
const buttonBase = "flex min-h-12 flex-1 items-center justify-center rounded-xl px-4 text-sm font-black transition-transform active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45";

export default function Wallet() {
  const { player, refresh } = usePlayer();
  const balance = walletValue(player?.play_wallet);
  const [modal, setModal] = useState<"deposit" | "withdraw" | null>(null);
  const [step, setStep] = useState(1);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [transactionsLoading, setTransactionsLoading] = useState(true);
  const [depositConfig, setDepositConfig] = useState<DepositConfig>({});
  const [deposit, setDeposit] = useState<DepositValues>({ name: "", amount: "", transactionId: "" });
  const [withdraw, setWithdraw] = useState<WithdrawValues>({ phone: "", name: "", amount: "" });
  const cacheAt = useRef(0);

  const loadTransactions = useCallback(async () => {
    const id = player?.user_id;
    if (!id || Date.now() - cacheAt.current < 15000) return;
    setTransactionsLoading(true);
    try {
      const [deposits, withdrawals] = await Promise.all([playerApi.deposits(id), playerApi.withdrawals(id)]);
      const all = [...deposits.map((item) => ({ ...item, type: "deposit" })), ...withdrawals.map((item) => ({ ...item, type: "withdraw" }))]
        .sort((a, b) => new Date(String(b.created_at || 0)).getTime() - new Date(String(a.created_at || 0)).getTime());
      setTransactions(all.slice(0, 8));
      cacheAt.current = Date.now();
    } catch { setTransactions([]); }
    finally { setTransactionsLoading(false); }
  }, [player?.user_id]);

  useEffect(() => { void loadTransactions(); }, [loadTransactions]);

  function openModal(kind: "deposit" | "withdraw") {
    setNotice("");
    setFormError("");
    if (kind === "withdraw") setWithdraw({ phone: player?.phone || "", name: player?.first_name || "", amount: "" });
    setModal(kind);
  }

  async function openDeposit() {
    if (!player?.user_id) { setNotice("Open KelemBingo from Telegram to use your wallet."); return; }
    setBusy(true); setNotice(""); setFormError("");
    try {
      const config = await playerApi.depositConfig(player.user_id);
      setDepositConfig(config);
      if (!config.ok) { setNotice(config.error === "too_many_pending" ? "You already have too many pending deposits." : config.error === "admin_offline" ? "Admin is offline. Please try again later." : "Deposit is not available right now."); return; }
      setDeposit((old) => ({ ...old, name: player.first_name || "" }));
      setStep(1);
      setModal("deposit");
    } catch (error) { setNotice(formatGatewayError(error, "Could not load deposit settings")); }
    finally { setBusy(false); }
  }

  function nextDepositStep() {
    const name = deposit.name.trim();
    const amount = Number(deposit.amount);
    if (!name) return setFormError("Enter the full name shown on the TeleBirr account.");
    if (!Number.isFinite(amount) || amount < 10) return setFormError("The minimum deposit is 10 ETB.");
    setFormError("");
    setStep(2);
  }

  async function submitDeposit() {
    const name = deposit.name.trim(); const amount = Number(deposit.amount); const transactionId = deposit.transactionId.trim();
    if (!name || !Number.isFinite(amount) || amount < 10 || transactionId.length < 3) { setFormError("Enter a TeleBirr name, at least 10 ETB, and a valid transaction number."); return; }
    setBusy(true);
    try { await playerApi.submitDeposit({ telebirr_name: name, amount, transaction_id: transactionId }); setNotice("Deposit request submitted."); setModal(null); cacheAt.current = 0; await Promise.all([refresh(), loadTransactions()]); }
    catch (error) { setFormError(formatGatewayError(error, "Could not submit deposit")); }
    finally { setBusy(false); }
  }

  async function submitWithdrawal() {
    const amount = Number(withdraw.amount); const phone = withdraw.phone.trim(); const name = withdraw.name.trim();
    if (!Number.isFinite(amount) || amount < 50) { setFormError("The minimum withdrawal is 50 ETB."); return; }
    if (amount > balance) { setFormError("The amount is greater than your available wallet balance."); return; }
    if (!/^\+?[0-9 ]{9,16}$/.test(phone)) { setFormError("Enter a valid TeleBirr phone number."); return; }
    if (!name) { setFormError("Enter the full name shown on the TeleBirr account."); return; }
    setBusy(true); const key = `withdrawal:${crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;
    try {
      const response = await playerApi.createWithdrawal({ amount, phone, telebirr_name: name }, key);
      if (response.ok === false || response.error) { const messages: Record<string, string> = { below_min: `Minimum withdrawal: ${response.min || 50} ETB.`, insufficient: "Insufficient balance.", pending_exists: "You already have a pending withdrawal.", system_error: "Server error validating withdrawal. Try again." }; const errorCode = typeof response.error === "string" ? response.error : ""; throw new Error(messages[errorCode] || formatGatewayError(response.error || response.message, "Withdrawal request failed.")); }
      setNotice("Withdrawal request submitted."); setModal(null); cacheAt.current = 0; await Promise.all([refresh(), loadTransactions()]);
    } catch (error) { setFormError(formatGatewayError(error, "Could not submit withdrawal")); }
    finally { setBusy(false); }
  }

  return <div className="min-h-[calc(100vh-56px)] bg-[linear-gradient(180deg,#0D1117_0%,#0A1628_40%,#111827_100%)] px-4 py-4"><h2 className="mb-4 text-xl font-bold text-white">Wallet</h2><div className="mb-4 rounded-2xl border border-white/10 bg-[#1A1A2E]/75 p-5 text-center shadow-[0_18px_45px_rgba(0,0,0,0.2)]"><div className="mb-1 text-xs uppercase tracking-wider text-white/50">Wallet Balance</div><div className="text-4xl font-black text-[#10B981]">{balance.toLocaleString()} ETB</div><p className="mt-2 text-[10px] text-white/30">Deposits and withdrawals are reviewed through TeleBirr.</p></div><div className="mb-6 grid grid-cols-2 gap-3"><button onClick={() => void openDeposit()} disabled={busy} className="rounded-2xl bg-gradient-to-br from-[#10B981] to-[#059669] p-4 text-center shadow-[0_8px_25px_rgba(16,185,129,0.25)] transition-transform active:scale-[0.97] disabled:opacity-50"><ArrowDownToLine className="mx-auto mb-2 h-5 w-5 text-white" /><div className="text-sm font-semibold text-white">Deposit</div><div className="mt-1 text-[10px] text-white/70">Add ETB balance</div></button><button onClick={() => openModal("withdraw")} disabled={busy} className="rounded-2xl bg-gradient-to-br from-[#EF4444] to-[#F97316] p-4 text-center shadow-[0_8px_25px_rgba(239,68,68,0.22)] transition-transform active:scale-[0.97] disabled:opacity-50"><ArrowUpFromLine className="mx-auto mb-2 h-5 w-5 text-white" /><div className="text-sm font-semibold text-white">Withdraw</div><div className="mt-1 text-[10px] text-white/70">Send to TeleBirr</div></button></div>{notice && <div className="mb-4 flex items-start gap-2 rounded-xl border border-[#F59E0B]/20 bg-[#F59E0B]/10 px-3 py-2 text-xs text-[#FCD34D]" role="status"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}<h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/70">Recent Transactions</h3>{transactionsLoading ? <div className="rounded-xl border border-white/10 bg-[#1A1A2E]/70 p-4 text-center"><Loader2 className="mx-auto h-4 w-4 animate-spin text-white/30" /></div> : transactions.length ? <div className="space-y-2">{transactions.map((item, index) => <div key={item.id || index} className="flex items-center justify-between rounded-xl border border-white/10 bg-[#1A1A2E]/70 px-4 py-3"><div><p className="text-xs font-black capitalize">{item.type || "transaction"}</p><p className="mt-1 text-[10px] uppercase text-white/35">{item.status || "pending"} · {relativeDate(item.created_at)}</p></div><p className={`text-sm font-black ${item.type === "withdraw" ? "text-[#FFB45C]" : "text-[#34D399]"}`}>{item.type === "withdraw" ? "−" : "+"}{etb(item.amount)}</p></div>)}</div> : <div className="rounded-xl border border-white/10 bg-[#1A1A2E]/70 p-4 text-center"><p className="text-sm text-white/30">No transactions yet</p></div>}{modal === "deposit" && <DepositModal step={step} setStep={setStep} values={deposit} setValues={setDeposit} config={depositConfig} busy={busy} error={formError} onClose={() => setModal(null)} onSubmit={() => void submitDeposit()} onNext={nextDepositStep} />}{modal === "withdraw" && <WithdrawModal values={withdraw} setValues={setWithdraw} busy={busy} balance={balance} error={formError} onClose={() => setModal(null)} onSubmit={() => void submitWithdrawal()} />}</div>;
}

function DepositModal({ step, setStep, values, setValues, config, busy, error, onClose, onSubmit, onNext }: { step: number; setStep: (step: number) => void; values: DepositValues; setValues: (value: DepositValues) => void; config: DepositConfig; busy: boolean; error: string; onClose: () => void; onSubmit: () => void; onNext: () => void }) {
  return <Modal title="Deposit Funds" subtitle="Follow the same TeleBirr deposit flow from the bot." error={error} onClose={onClose}>{step === 1 ? <><PendingCard count={config.pending_count} limit={config.pending_limit} /><Field label="TeleBirr full name" htmlFor="deposit-name"><Input id="deposit-name" value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} placeholder="Name on TeleBirr account" autoComplete="name" className={inputClass} /></Field><Field label="Amount" htmlFor="deposit-amount"><MoneyInput id="deposit-amount" value={values.amount} onChange={(amount) => setValues({ ...values, amount })} min={10} placeholder="0.00" accent="green" /></Field><div className="mt-5 flex gap-3"><button onClick={onClose} className={`${buttonBase} border border-white/10 bg-white/[0.06] text-white/70`}>Cancel</button><button onClick={onNext} className={`${buttonBase} bg-gradient-to-r from-[#10B981] to-[#059669] text-white`}>Next</button></div></> : <><div className="rounded-xl border border-[#14B8A6]/25 bg-[#14B8A6]/[0.08] p-4"><div className="text-[10px] font-black uppercase tracking-wider text-white/45">Send to TeleBirr number</div><div className="mt-1 text-xl font-black text-[#2DD4BF]">{config.phone || "—"}</div><p className="mt-2 text-xs leading-5 text-white/50">Send {values.amount || "the amount"} ETB first, then enter the transaction number from your receipt.</p></div><Field label="Transaction number" htmlFor="deposit-transaction"><Input id="deposit-transaction" value={values.transactionId} onChange={(event) => setValues({ ...values, transactionId: event.target.value })} placeholder="Receipt transaction number" autoComplete="off" className={inputClass} /></Field><div className="mt-5 flex gap-3"><button onClick={() => { setStep(1); }} className={`${buttonBase} border border-white/10 bg-white/[0.06] text-white/70`}>Back</button><button onClick={onSubmit} disabled={busy} className={`${buttonBase} bg-gradient-to-r from-[#10B981] to-[#059669] text-white`}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit request"}</button></div></>}</Modal>;
}

function WithdrawModal({ values, setValues, busy, balance, error, onClose, onSubmit }: { values: WithdrawValues; setValues: (value: WithdrawValues) => void; busy: boolean; balance: number; error: string; onClose: () => void; onSubmit: () => void }) { return <Modal title="Withdraw Funds" subtitle="Withdrawals are sent to your TeleBirr account." error={error} onClose={onClose}><div className="mb-4 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.08] p-4 text-center"><div className="text-[10px] font-black uppercase tracking-wider text-white/45">Available balance</div><div className="mt-1 text-xl font-black text-[#34D399]">{etb(balance)}</div></div><div className="space-y-3"><Field label="Amount" htmlFor="withdraw-amount"><MoneyInput id="withdraw-amount" value={values.amount} onChange={(amount) => setValues({ ...values, amount })} min={50} max={balance} placeholder="0.00" accent="orange" /></Field><Field label="TeleBirr phone number" htmlFor="withdraw-phone"><Input id="withdraw-phone" type="tel" value={values.phone} onChange={(event) => setValues({ ...values, phone: event.target.value })} placeholder="+251 911 000 000" inputMode="tel" autoComplete="tel" className={inputClass} /></Field><Field label="TeleBirr full name" htmlFor="withdraw-name"><Input id="withdraw-name" value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} placeholder="Name on TeleBirr account" autoComplete="name" className={inputClass} /></Field><div className="mt-5 flex gap-3"><button onClick={onClose} className={`${buttonBase} border border-white/10 bg-white/[0.06] text-white/70`}>Cancel</button><button onClick={onSubmit} disabled={busy} className={`${buttonBase} bg-gradient-to-r from-[#F97316] to-[#EF4444] text-white`}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit request"}</button></div></div></Modal>; }

function PendingCard({ count = 0, limit = 3 }: { count?: number; limit?: number }) { return <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4 text-center"><div className="text-[10px] font-black uppercase tracking-wider text-white/45">Pending deposit requests</div><div className="mt-1 text-2xl font-black text-[#34D399]">{count} <span className="text-sm text-white/35">/ {limit}</span></div><div className="mt-1 text-[10px] text-white/30">Keep requests below the review limit.</div></div>; }
function MoneyInput({ id, value, onChange, min, max, placeholder, accent }: { id: string; value: string; onChange: (value: string) => void; min: number; max?: number; placeholder: string; accent: "green" | "orange" }) { return <div className="relative"><Input id={id} type="number" min={min} max={max} step="0.01" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} inputMode="decimal" className={`${inputClass} pr-16 ${accent === "green" ? "focus-visible:border-[#10B981] focus-visible:ring-[#10B981]/25" : "focus-visible:border-[#FF8C00]"}`} /><span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-xs font-black text-white/35">ETB</span></div>; }
function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) { return <label htmlFor={htmlFor} className="mt-4 block text-[10px] font-black uppercase tracking-[0.12em] text-white/50">{label}<span className="mt-1.5 block normal-case tracking-normal">{children}</span></label>; }
function Modal({ title, subtitle, error, children, onClose }: { title: string; subtitle?: string; error?: string; children: React.ReactNode; onClose: () => void }) { return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}><DialogContent showCloseButton={false} className="max-h-[88vh] max-w-[380px] overflow-y-auto rounded-3xl border-white/10 bg-[#1A1A2E]/[0.98] p-5 text-white shadow-[0_25px_70px_rgba(0,0,0,0.55)]"><DialogHeader className="mb-1 pr-8 text-left"><DialogTitle className="text-xl font-black text-white">{title}</DialogTitle>{subtitle && <DialogDescription className="mt-1 text-xs leading-5 text-white/45">{subtitle}</DialogDescription>}</DialogHeader><button onClick={onClose} className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/[0.06] text-white/60 transition-colors hover:text-white" aria-label="Close"><X className="h-4 w-4" /></button>{error && <div className="mt-3 rounded-xl border border-red-400/25 bg-red-500/10 px-3 py-2.5 text-xs leading-5 text-red-200" role="alert">{error}</div>}<div className="mt-2">{children}</div></DialogContent></Dialog>; }
