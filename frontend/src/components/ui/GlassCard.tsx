/**
 * frontend/src/components/ui/GlassCard.tsx
 *
 * Reference component — establishes every design pattern for the Harmonia UI.
 *
 * This is the most-used primitive in the app. Album cards, search result cards,
 * the tagging panel, the settings screen — all of them are GlassCard variants.
 * Read this file before writing any other component.
 *
 * Patterns established here that ALL other components must follow:
 *
 *   1. Glassmorphism surface: backdrop-blur-glass + bg-white/[.06] + border border-white/[.08]
 *      Never use a solid background for a card. Never use border-white/10 (too harsh).
 *
 *   2. Purple accent for interactive states: hover uses accent-400/20 fill,
 *      focus uses shadow-glow-accent ring. Never use blue or generic grey for focus.
 *
 *   3. Gold for emphasis: confidence scores, star ratings, "now playing" indicator.
 *      Never use yellow-* from the default Tailwind palette — always gold-*.
 *
 *   4. Text hierarchy: text-text-primary → text-text-secondary → text-text-tertiary.
 *      Never use text-white (too harsh on navy) or text-gray-* (wrong palette).
 *
 *   5. Radius tokens: rounded-card (16px) for cards, rounded-sheet (24px) for
 *      sheets/drawers, rounded-pill for tags. Never use rounded-xl directly.
 *
 *   6. Motion: framer-motion with spring easing for all layout transitions.
 *      CSS transitions use transition-spring for hover states.
 *      No bounce on iOS — ease-out-expo for sheet entry.
 *
 *   7. Composition over configuration: use the `variant` prop to switch between
 *      card styles, not a separate component per variant.
 *
 *   8. className always last in the spread — allows callers to override tokens.
 *
 * Exported components:
 *   GlassCard        — base surface primitive
 *   GlassCardHeader  — title + optional subtitle
 *   GlassCardBadge   — pill badge (confidence, source, status)
 *   ConfidenceBar    — tagging panel confidence indicator (green/gold/red)
 */

"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CardVariant =
  | "default"      // standard glass card (album cards, search results)
  | "elevated"     // modals and sheets (heavier blur)
  | "interactive"  // clickable cards with hover/press states
  | "selected"     // currently selected / active state
  | "inset";       // sunken surface (input backgrounds, nested panels)

type BadgeVariant =
  | "accent"   // purple — source badges, plugin labels
  | "gold"     // gold — confidence scores, ratings
  | "success"  // emerald — confirmed, library_ready
  | "warning"  // gold-tinted — medium confidence, pending
  | "danger"   // red — errors, low confidence
  | "ghost";   // translucent — neutral labels

// ---------------------------------------------------------------------------
// GlassCard
// ---------------------------------------------------------------------------

interface GlassCardProps extends HTMLMotionProps<"div"> {
  variant?: CardVariant;
  /** Adds a subtle purple glow ring — use for "now playing" or selected state */
  glowing?: boolean;
  /** Adds a gold glow ring — use for high-confidence tagging suggestions */
  goldGlow?: boolean;
}

export function GlassCard({
  variant = "default",
  glowing = false,
  goldGlow = false,
  className,
  children,
  ...props
}: GlassCardProps) {
  return (
    <motion.div
      className={cn(
        // Base glass surface
        "relative rounded-card border backdrop-blur-glass",

        // Variant fills
        variant === "default"      && "bg-white/[.06] border-white/[.08]",
        variant === "elevated"     && "bg-white/[.08] border-white/[.10] backdrop-blur-sheet",
        variant === "interactive"  && [
          "bg-white/[.06] border-white/[.08] cursor-pointer",
          "hover:bg-white/[.09] hover:border-white/[.12]",
          "active:bg-white/[.05] active:scale-[0.99]",
          "transition-all duration-200 ease-spring",
        ],
        variant === "selected"     && "bg-accent-400/[.15] border-accent-400/[.40]",
        variant === "inset"        && "bg-black/[.20] border-white/[.05]",

        // Glow rings
        glowing   && "shadow-glow-accent",
        goldGlow  && "shadow-glow-gold",

        // Shared shadow
        "shadow-glass",

        className,
      )}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// GlassCardHeader
// ---------------------------------------------------------------------------

interface GlassCardHeaderProps {
  title: string;
  subtitle?: string;
  /** Rendered in the top-right corner — use for badges, timestamps, actions */
  action?: React.ReactNode;
  className?: string;
}

export function GlassCardHeader({
  title,
  subtitle,
  action,
  className,
}: GlassCardHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-3", className)}>
      <div className="min-w-0 flex-1">
        <p className="truncate text-track-title text-text-primary">
          {title}
        </p>
        {subtitle && (
          <p className="mt-0.5 truncate text-track-meta text-text-secondary">
            {subtitle}
          </p>
        )}
      </div>
      {action && (
        <div className="shrink-0">
          {action}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GlassCardBadge
// ---------------------------------------------------------------------------

interface GlassCardBadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

export function GlassCardBadge({
  children,
  variant = "ghost",
  className,
}: GlassCardBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-pill px-2 py-0.5 text-label font-medium",

        variant === "accent"  && "bg-accent-400/20 text-accent-300 ring-1 ring-accent-400/30",
        variant === "gold"    && "bg-gold-400/20   text-gold-300   ring-1 ring-gold-400/30",
        variant === "success" && "bg-success/20    text-success    ring-1 ring-success/30",
        variant === "warning" && "bg-warning/20    text-gold-300   ring-1 ring-warning/30",
        variant === "danger"  && "bg-danger/20     text-danger     ring-1 ring-danger/30",
        variant === "ghost"   && "bg-white/[.08]   text-text-secondary",

        className,
      )}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ConfidenceBar
// ---------------------------------------------------------------------------
// Shown at the top of the tagging panel.
// Green ≥ 85%, Gold 60–84%, Red < 60% — as specified in Architecture §6.4.

interface ConfidenceBarProps {
  /** Confidence value between 0.0 and 1.0 */
  confidence: number;
  className?: string;
}

export function ConfidenceBar({ confidence, className }: ConfidenceBarProps) {
  const percent = Math.round(confidence * 100);

  const tier =
    percent >= 85 ? "high" :
    percent >= 60 ? "medium" :
    "low";

  const trackColor =
    tier === "high"   ? "bg-success" :
    tier === "medium" ? "bg-gold-400" :
    "bg-danger";

  const labelColor =
    tier === "high"   ? "text-success" :
    tier === "medium" ? "text-gold-400" :
    "text-danger";

  const glowClass =
    tier === "high"   ? "shadow-glow-success" :
    tier === "medium" ? "shadow-glow-warning" :
    "shadow-glow-danger";

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between">
        <span className="text-label text-text-tertiary uppercase tracking-wider">
          Match confidence
        </span>
        <span className={cn("text-label font-medium", labelColor)}>
          {percent}%
        </span>
      </div>

      {/* Track */}
      <div className="h-1.5 w-full overflow-hidden rounded-pill bg-white/[.08]">
        <motion.div
          className={cn("h-full rounded-pill", trackColor, glowClass)}
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usage example (not exported — for reference only)
// ---------------------------------------------------------------------------
//
// import { GlassCard, GlassCardHeader, GlassCardBadge, ConfidenceBar } from "@/components/ui/GlassCard";
//
// // Search result card
// <GlassCard variant="interactive" onClick={() => onSelect(result)}>
//   <div className="flex gap-3 p-3">
//     <img src={result.thumbnailUrl} className="h-12 w-12 rounded-card object-cover" />
//     <GlassCardHeader
//       title={result.title}
//       subtitle={result.artist}
//       action={
//         <GlassCardBadge variant="accent">
//           {result.sourcePlugin}
//         </GlassCardBadge>
//       }
//     />
//   </div>
// </GlassCard>
//
// // Tagging panel header
// <GlassCard variant="elevated" className="p-4">
//   <ConfidenceBar confidence={0.87} className="mb-4" />
//   <GlassCardHeader title="Never Gonna Give You Up" subtitle="Rick Astley" />
// </GlassCard>
//
// // Now playing (gold glow)
// <GlassCard variant="interactive" goldGlow className="p-3">
//   <GlassCardHeader
//     title={track.title}
//     subtitle={track.artist}
//     action={<GlassCardBadge variant="gold">Playing</GlassCardBadge>}
//   />
// </GlassCard>
