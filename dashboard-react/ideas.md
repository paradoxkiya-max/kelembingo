# KelemBingo React rebuild — ground-truth design reference

This is a replication-focused rebuild. The existing KelemBingo player Mini App and admin dashboard are the visual source of truth; fidelity to their current dark glass UI, compact mobile geometry, orange-led action hierarchy, and bingo-specific semantic colors takes precedence over introducing a new visual direction.

## Ground-truth reference

The player app uses a `#0D1117` background, deep navy glass surfaces, backdrop blur, thin translucent borders, Inter typography, orange primary actions, and compact statistic pills. The visual language is energetic but information-dense: orange indicates action and selection, green indicates success/marked cards, red indicates danger or time pressure, blue/purple/teal support metrics, and the B/I/N/G/O columns retain their established colors.

The mobile player shell is intentionally narrow and touch-first. Home, history, wallet, and profile use a fixed Telegram-style header and bottom navigation. Card selection is an immersive full-height surface with an eight-column card grid, selection summary, timer bar, and inline previews. The game board remains side-by-side, with a 45% master-number grid and 55% player-card/announcement area. The admin dashboard uses a fixed sidebar, glass header, responsive mobile drawer, operational tables, charts, status badges, and modal confirmations.

## Implementation decisions

React components will replace DOM fragments and global handlers, while preserving the existing API routes, player-token header, Socket.IO events, timer semantics, financial safeguards, and page behavior. Tailwind utilities will express the existing visual tokens; small CSS additions will be reserved for the high-frequency game grid, audio state, and performance containment. Motion will remain short and purposeful, with reduced-motion fallbacks.

## Brand mark

The existing orange “B” mark is retained as the recognizable KelemBingo symbol. The rebuild may use a generated transparent Bingo mark only where it improves fidelity, but it must remain a bold symbol without replacing the existing wordmark or altering the established orange identity.

## Style decisions

- Preserve the dark glass and orange-led visual hierarchy rather than introducing a new theme.
- Keep the player’s compact 420px-centered geometry and side-by-side game board behavior.
- Keep the admin’s persistent sidebar and data-dense operational layout.
- Improve semantics, focus states, and live regions without changing visual meaning.
- Do not introduce decorative imagery that conflicts with the existing product UI.
