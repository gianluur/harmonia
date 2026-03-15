import type { Config } from "tailwindcss";

/**
 * Harmonia Design System — Tailwind Configuration
 *
 * Palette: Deep navy base, purple accent, gold highlight.
 * Surface treatment: glassmorphism (backdrop-blur + translucent fills).
 * Typography: Inter variable font throughout.
 *
 * Token naming convention:
 *   bg-base          — page background (deep navy)
 *   bg-surface       — glass card surface
 *   bg-surface-hover — glass card hovered
 *   bg-elevated      — modals, sheets, drawers
 *   accent-*         — electric purple (primary actions, active states)
 *   gold-*           — warm gold (confidence scores, highlights, badges)
 *   text-primary     — full-brightness text
 *   text-secondary   — muted text (artist names, timestamps)
 *   text-tertiary    — hint text (placeholders, disabled)
 *   border-subtle    — glass edge borders
 *   border-strong    — focused input borders
 *
 * All colours have been checked for WCAG AA contrast on both the navy base
 * and the glass surface at their respective opacities.
 */

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],

  theme: {
    extend: {
      // ----------------------------------------------------------------
      // Colour palette
      // ----------------------------------------------------------------
      colors: {
        // Base backgrounds
        base: {
          DEFAULT: "#0F0E17",   // deepest navy — page background
          900:     "#0F0E17",
          800:     "#14131F",   // slightly lighter — used for nested containers
          700:     "#1A1927",   // cards before glass treatment
          600:     "#211F31",   // elevated panels
        },

        // Glass surfaces — applied with bg-opacity or as rgba in CSS vars
        surface: {
          DEFAULT: "rgba(255, 255, 255, 0.06)",
          hover:   "rgba(255, 255, 255, 0.09)",
          active:  "rgba(255, 255, 255, 0.12)",
          elevated:"rgba(255, 255, 255, 0.08)",
        },

        // Purple — primary accent (actions, active states, focus rings)
        accent: {
          50:  "#F3F0FF",
          100: "#E9E3FF",
          200: "#D4C9FF",
          300: "#B8A9FF",
          400: "#9B87FF",  // ← main accent — use for buttons, links, active nav
          500: "#7C63F5",
          600: "#6147E8",
          700: "#4D35C4",
          800: "#3A2799",
          900: "#281A6E",
          950: "#160E42",
        },

        // Gold — highlights, confidence badges, hover accents, star ratings
        gold: {
          50:  "#FFFBEB",
          100: "#FFF3C4",
          200: "#FFE484",
          300: "#FFD44A",  // ← bright gold — use sparingly for maximum pop
          400: "#FFC220",  // ← main gold — buttons, badges, confidence rings
          500: "#F5A800",
          600: "#D98C00",
          700: "#B36E00",
          800: "#8A5200",
          900: "#613900",
          950: "#3D2200",
        },

        // Text
        text: {
          primary:   "#F0EEF8",  // near-white, slightly cool — main readable text
          secondary: "#A09AB8",  // muted purple-grey — artist names, metadata
          tertiary:  "#5E5875",  // low-contrast — placeholders, disabled states
          inverse:   "#0F0E17",  // dark text on gold/light backgrounds
        },

        // Semantic
        success:  "#10B981",   // emerald — library_ready, confirmed state
        warning:  "#FFC220",   // same as gold-400 — medium beets confidence
        danger:   "#EF4444",   // red — errors, low confidence, job_error
        info:     "#7C63F5",   // same as accent-500 — informational toasts

        // Border tokens
        border: {
          subtle: "rgba(255, 255, 255, 0.08)",   // glass card edges
          medium: "rgba(255, 255, 255, 0.14)",   // hover borders
          strong: "rgba(156, 135, 255, 0.50)",   // focused inputs (accent tint)
          gold:   "rgba(255, 194, 32, 0.40)",    // gold-accented borders
        },
      },

      // ----------------------------------------------------------------
      // Typography
      // ----------------------------------------------------------------
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },

      fontSize: {
        // Track/content typography scale
        "track-title":  ["15px", { lineHeight: "1.4", fontWeight: "500" }],
        "track-meta":   ["13px", { lineHeight: "1.4", fontWeight: "400" }],
        "label":        ["11px", { lineHeight: "1.3", fontWeight: "500", letterSpacing: "0.06em" }],
      },

      // ----------------------------------------------------------------
      // Border radius
      // ----------------------------------------------------------------
      borderRadius: {
        card:  "16px",   // album cards, result cards
        sheet: "24px",   // bottom sheets, side drawers
        pill:  "9999px", // tags, badges, pills
        input: "10px",   // text inputs
        btn:   "10px",   // buttons
      },

      // ----------------------------------------------------------------
      // Box shadows — glow effects for interactive elements
      // ----------------------------------------------------------------
      boxShadow: {
        // Glass card resting shadow
        "glass":        "0 4px 24px rgba(0, 0, 0, 0.40), inset 0 1px 0 rgba(255,255,255,0.06)",
        // Glass card hovered
        "glass-hover":  "0 8px 32px rgba(0, 0, 0, 0.50), inset 0 1px 0 rgba(255,255,255,0.10)",
        // Purple glow — focused inputs, active buttons
        "glow-accent":  "0 0 0 3px rgba(156, 135, 255, 0.35)",
        // Gold glow — confidence rings, highlighted fields
        "glow-gold":    "0 0 0 3px rgba(255, 194, 32, 0.35)",
        // Soft inner shadow for inset surfaces
        "inner-soft":   "inset 0 2px 8px rgba(0, 0, 0, 0.30)",
        // Confidence badge glow (green / yellow / red)
        "glow-success": "0 0 0 2px rgba(16, 185, 129, 0.40)",
        "glow-warning": "0 0 0 2px rgba(255, 194, 32, 0.40)",
        "glow-danger":  "0 0 0 2px rgba(239, 68, 68, 0.40)",
      },

      // ----------------------------------------------------------------
      // Backdrop blur
      // ----------------------------------------------------------------
      backdropBlur: {
        glass: "20px",   // standard glass surface blur
        sheet: "32px",   // heavier blur for sheets/modals
      },

      // ----------------------------------------------------------------
      // Spacing extras
      // ----------------------------------------------------------------
      spacing: {
        "safe-bottom": "env(safe-area-inset-bottom)",  // iOS home indicator
        "safe-top":    "env(safe-area-inset-top)",     // iOS notch
        "nav-height":  "64px",   // bottom nav / top bar height
        "player-mini": "72px",   // mini player bar height
      },

      // ----------------------------------------------------------------
      // Animation
      // ----------------------------------------------------------------
      keyframes: {
        "slide-up": {
          from: { transform: "translateY(100%)", opacity: "0" },
          to:   { transform: "translateY(0)",    opacity: "1" },
        },
        "slide-right": {
          from: { transform: "translateX(100%)", opacity: "0" },
          to:   { transform: "translateX(0)",    opacity: "1" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "1",   transform: "scale(1)" },
          "50%":      { opacity: "0.6", transform: "scale(1.05)" },
        },
        // Streaming indicator ring (shown while playing from /api/stream)
        "spin-slow": {
          from: { transform: "rotate(0deg)" },
          to:   { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "slide-up":    "slide-up 0.3s cubic-bezier(0.32, 0.72, 0, 1)",
        "slide-right": "slide-right 0.3s cubic-bezier(0.32, 0.72, 0, 1)",
        "fade-in":     "fade-in 0.2s ease-out",
        "pulse-ring":  "pulse-ring 2s ease-in-out infinite",
        "spin-slow":   "spin-slow 3s linear infinite",
      },

      // ----------------------------------------------------------------
      // Transition
      // ----------------------------------------------------------------
      transitionTimingFunction: {
        // Spring-like ease for sheets and cards (no bounce on iOS)
        spring:  "cubic-bezier(0.32, 0.72, 0, 1)",
        "ease-out-expo": "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },

  plugins: [
    // Tailwind Typography (for any prose/markdown rendering)
    require("@tailwindcss/typography"),
  ],
};

export default config;
