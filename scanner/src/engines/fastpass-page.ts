/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

export interface PageStop {
  id: number;
  selector: string;
  html: string;
  top: number;
  bottom: number;
  visible: boolean;
  pinned: boolean;
  frameLike: boolean;
  positiveTabindex: boolean;
  inModal: boolean;
  outline: "author-ok" | "ua-default" | "other";
}

export interface PageTarget {
  selector: string;
  html: string;
  roleWidget: boolean;
  hasTabindex: boolean;
}

export interface StepResult {
  stop: PageStop | null;
  prevChanged: boolean | null;
}

// Runs inside the page via page.evaluate(): self-contained, no imports or module-level references.
// Helpers are object methods on purpose: tsx injects __name into named functions, absent in the page.
export function installFastpassHelpers(key: string): void {
  const h = {
    seen: [] as Element[],
    focusedSnap: new Map<number, [Element, string][]>(),
    widgetRoles: "button,link,checkbox,switch,slider,spinbutton,textbox,searchbox,combobox",
    focusable:
      "a[href],area[href],button,input:not([type=hidden]),select,textarea,summary,iframe,[contenteditable]:not([contenteditable=false]),[tabindex]",

    active(): Element | null {
      let el = document.activeElement;
      while (el?.shadowRoot?.activeElement) el = el.shadowRoot.activeElement;
      return el === document.body || el === document.documentElement ? null : el;
    },

    selector(el: Element): string {
      const parts: string[] = [];
      let e: Element | null = el;
      for (let i = 0; e && i < 5; i++) {
        if (e.id) return ["#" + CSS.escape(e.id), ...parts].join(" > ");
        parts.unshift(h.position(e));
        e = e.parentElement;
      }
      return parts.join(" > ");
    },

    position(e: Element): string {
      const same = e.parentElement ? [...e.parentElement.children].filter((c) => c.localName === e.localName) : [e];
      return same.length > 1 ? `${e.localName}:nth-of-type(${same.indexOf(e) + 1})` : e.localName;
    },

    related(el: Element): Element[] {
      const out = [el, el.parentElement, el.nextElementSibling];
      if ("labels" in el && el.labels) out.push(...(el.labels as NodeListOf<HTMLLabelElement>));
      return out.filter((e): e is Element => e !== null && e !== document.body);
    },

    // Finish finite transitions, or computed styles show a mid-transition look.
    settle(el: Element): void {
      for (const e of h.related(el))
        for (const a of e.getAnimations({ subtree: e === el }))
          if (Number.isFinite(Number(a.effect?.getComputedTiming().endTime))) a.finish();
    },

    look(e: Element, pseudo: string | null): string {
      const s = getComputedStyle(e, pseudo);
      return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.outlineOffset, s.boxShadow, s.borderColor,
        s.borderWidth, s.backgroundColor, s.backgroundImage, s.color, s.textDecorationLine, s.opacity, s.transform].join("|");
    },

    snapshot(el: Element): [Element, string][] {
      h.settle(el);
      const self = h.look(el, null) + h.look(el, "::before") + h.look(el, "::after");
      return [[el, self], ...h.related(el).slice(1).map((e): [Element, string] => [e, h.look(e, null)])];
    },

    changed(prev: Element, now: Element | null): boolean {
      const before = h.focusedSnap.get(h.seen.indexOf(prev)) ?? [];
      const after = h.snapshot(prev);
      return before.some(([e, look], i) => {
        // Elements tied to the new focus changed because of it, not because prev lost focus.
        const tied = now !== null && e !== prev && (e === now || e.contains(now) || now.contains(e));
        return !tied && after[i]?.[1] !== look;
      });
    },

    luminance(color: string): number | null {
      const m = /^rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)$/.exec(color);
      if (!m || Number(m[4] ?? 1) < 1) return null;
      const [r, g, b] = [m[1], m[2], m[3]].map((v) => {
        const c = Number(v) / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
    },

    background(el: Element): string {
      for (let e: Element | null = el.parentElement; e; e = e.parentElement) {
        const bg = getComputedStyle(e).backgroundColor;
        if (bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
      }
      return "rgb(255, 255, 255)";
    },

    // WCAG 2.2 SC 2.4.13: author outline ≥ 2px at 3:1 against the background.
    outline(el: Element): PageStop["outline"] {
      const s = getComputedStyle(el);
      if (s.outlineStyle === "auto") return "ua-default";
      if (s.outlineStyle === "none" || parseFloat(s.outlineWidth) < 2) return "other";
      const a = h.luminance(s.outlineColor);
      const b = h.luminance(h.background(el));
      if (a === null || b === null) return "other";
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 3 ? "author-ok" : "other";
    },

    pinned(el: Element): boolean {
      for (let e: Element | null = el; e; e = e.parentElement)
        if (/fixed|sticky/.test(getComputedStyle(e).position)) return true;
      return false;
    },

    describe(el: Element, id: number): PageStop {
      const r = el.getBoundingClientRect();
      const visible = r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
      return {
        id,
        selector: h.selector(el),
        html: el.outerHTML.slice(0, 400),
        top: r.top + scrollY,
        bottom: r.bottom + scrollY,
        visible,
        pinned: h.pinned(el),
        frameLike: /^(iframe|frame|object|embed)$/.test(el.localName) || el.localName.includes("-"),
        positiveTabindex: (el as HTMLElement).tabIndex > 0,
        inModal: el.closest("dialog[open],[aria-modal=true],[role=alertdialog]") !== null,
        outline: h.outline(el),
      };
    },

    step(prevId: number): StepResult {
      const el = h.active();
      const prev = h.seen[prevId];
      const prevChanged = prev && prev !== el ? h.changed(prev, el) : null;
      if (!el) return { stop: null, prevChanged };
      let id = h.seen.indexOf(el);
      if (id < 0) id = h.seen.push(el) - 1;
      h.focusedSnap.set(id, h.snapshot(el));
      return { stop: h.describe(el, id), prevChanged };
    },

    target(el: Element): PageTarget {
      return {
        selector: h.selector(el),
        html: el.outerHTML.slice(0, 400),
        roleWidget: el.matches(h.widgetRoles.split(",").map((r) => `[role=${r}]`).join(",")),
        hasTabindex: el.hasAttribute("tabindex"),
      };
    },

    shown(el: Element): boolean {
      return el.checkVisibility({ visibilityProperty: true }) && el.closest("[inert]") === null;
    },

    nonFocusable(limit: number): PageTarget[] {
      const roles = h.widgetRoles.split(",").map((r) => `[role=${r}]`).join(",");
      return [...document.querySelectorAll(`${roles},[onclick]:not(body,html,label)`)]
        .filter((el) => (el as HTMLElement).tabIndex < 0 && h.shown(el) && !el.matches(":disabled,[aria-disabled=true]"))
        .filter((el) => el.parentElement?.closest(`${h.focusable},[aria-activedescendant]`) == null)
        .slice(0, limit)
        .map((el) => h.target(el));
    },

    // Radios are skipped: a radio group is one Tab stop.
    unreached(limit: number): PageTarget[] {
      return [...document.querySelectorAll(h.focusable)]
        .filter((el) => (el as HTMLElement).tabIndex >= 0 && !el.matches(":disabled,input[type=radio]"))
        .filter((el) => h.shown(el) && !h.seen.includes(el))
        .slice(0, limit)
        .map((el) => h.target(el));
    },

    focusNeighbour(id: number): boolean {
      const n = h.seen[id] as HTMLElement | undefined;
      n?.focus({ preventScroll: false });
      return n !== undefined && h.active() === n;
    },

    blur(): boolean {
      (h.active() as HTMLElement | null)?.blur?.();
      return h.active() === null;
    },
  };
  (window as unknown as Record<string, unknown>)[key] = h;
}
