# KelemBingo UI parity direction

## Ground-truth reference

The supplied Telegram Mini App screenshots and the legacy static UI from commit `6f299cf` are the binding design specification. This is a replication task, so no alternative stylistic approaches are being considered. Fidelity to the old layout overrides generic dashboard patterns and the newer React approximation.

## Design movement

Compact Telegram-native dark glass game interface with arcade bingo color coding and mobile-first information density.

## Core principles

The React UI must preserve the legacy vertical rhythm, the full-width 591×1280 mobile composition, the fixed Telegram header and bottom navigation, and the dense game-board geometry. Visual emphasis must come from the original B/I/N/G/O colors, green wallet/success states, orange actions, purple high-stakes states, translucent borders, and restrained glow rather than new gradients or oversized cards.

## Layout paradigm

Use a full-width mobile canvas with a 56px Telegram header, screen-specific content padding, and a fixed bottom navigation on player screens. The home screen follows the legacy vertical stack. Cartela selection uses a dense 8-column grid plus selected-card preview and bottom summary. Live play uses the original 45% called-number board / 55% cartela stack split. Modals use the old centered dark-glass geometry and field spacing.

## Signature elements

The five bingo column colors, the orange cartela header, the three-card live stats row, and the fixed four-item Game/History/Wallet/Profile navigation must recur consistently. The Telegram close/overflow header remains compact and visually separate from the game content.

## Interaction philosophy

Every interaction should feel immediate and touch-sized, but all financial and game outcomes remain server-authoritative. Optimistic selection is allowed only when it can roll back on gateway failure. Timers use server timestamps; realtime events update the same screen state without duplicate subscriptions or competing timers.

## Typography system

Keep Inter and the legacy scale: compact uppercase micro-labels, 10–12px metadata, 14–18px card headings, and bold numeric values. Do not introduce a new desktop dashboard hierarchy into player screens.

## Brand essence

KelemBingo is a Telegram-native Ethiopian bingo game for fast, transparent ETB rounds, differentiated by live multiplayer play, visible Derash math, and a compact arcade board. Personality: **direct, energetic, trustworthy**.

## Brand voice

Headlines and labels stay short and operational. CTAs say what will happen: “Play a round,” “Confirm selection,” “Deposit,” “Withdraw,” “Leave,” and “AUTO.” Financial labels distinguish wallet balance, stake, Derash pool, and prize per winner without promotional filler.

## Signature brand color

KelemBingo orange `#FF8C00` is reserved for primary action, cartela headers, and selected game emphasis.
