// Style reminder: routing is a safe shell around the preserved dark-glass player experience; no route is a dead end.

import { Route, Switch, useLocation } from "wouter";
import { lazy, Suspense, useEffect } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import ErrorBoundary from "@/components/ErrorBoundary";
import { PlayerProvider } from "@/contexts/PlayerContext";
import { AdminProvider, useAdmin } from "@/contexts/AdminContext";
import PlayerShell from "@/components/player/PlayerShell";
import Home from "@/pages/Home";
const History = lazy(() => import("@/pages/History"));
const Wallet = lazy(() => import("@/pages/Wallet"));
const Profile = lazy(() => import("@/pages/Profile"));
import NotFound from "@/pages/NotFound";
const CartelaSelect = lazy(() => import("@/pages/CartelaSelect"));
const GameBoard = lazy(() => import("@/pages/GameBoard"));
const AdminLogin = lazy(() => import("@/pages/admin/AdminLogin"));
const AdminDashboard = lazy(() => import("@/pages/admin/AdminDashboard"));

function PlayerRouter() {
  return <PlayerShell><Suspense fallback={<div className="flex min-h-[calc(100vh-56px)] items-center justify-center text-sm text-white/35">Loading screen…</div>}><Switch><Route path="/" component={Home} /><Route path="/history" component={History} /><Route path="/wallet" component={Wallet} /><Route path="/profile" component={Profile} /><Route path="/select" component={CartelaSelect} /><Route path="/game" component={GameBoard} /><Route path="/404" component={NotFound} /><Route component={NotFound} /></Switch></Suspense></PlayerShell>;
}

function AdminRouter() { return <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-[#0D1117] text-white/40">Loading admin surface…</div>}><Switch><Route path="/admin/login" component={AdminLogin} /><Route path="/login" component={AdminLogin} /><Route path="/admin"><AdminGate /></Route><Route component={AdminLogin} /></Switch></Suspense>; }
function AdminGate() { const [, navigate] = useLocation(); const { admin, loading } = useAdmin(); useEffect(() => { if (!loading && !admin) navigate("/admin/login"); }, [admin, loading, navigate]); if (loading || !admin) return <div className="flex min-h-screen items-center justify-center bg-[#0D1117] text-white/40">Loading admin session…</div>; return <AdminDashboard />; }

function AppRouter() { const [location] = useLocation(); return location.startsWith("/admin") || location === "/login" ? <AdminProvider><AdminRouter /></AdminProvider> : <PlayerProvider><PlayerRouter /></PlayerProvider>; }

export default function App() { return <ErrorBoundary><TooltipProvider><Toaster /><AppRouter /></TooltipProvider></ErrorBoundary>; }
