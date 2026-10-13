import { useEffect, useMemo, useRef, useState } from "react";

// A dropdown with a search box and a scrolling list, for pickers that grow
// past what a plain <select> is usable for (contacts, plants).
//
// options: [{ value, label, hint?, search? }] -- `search` is extra text to
// match on (mobile number, SKU) that isn't shown as the label; `hint` is
// shown dimmed beside the label. The full list is filtered in the browser:
// every caller already loads its whole list, so nothing is ever cut off.
//
// value "" means nothing selected; pass `clearLabel` to offer that as a
// choice (e.g. "No linked plant...").
export default function SearchSelect({ id, options, value, onChange, placeholder, searchPlaceholder, emptyText, clearLabel }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const searchRef = useRef(null);
  const listRef = useRef(null);

  const selected = options.find((o) => String(o.value) === String(value));

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = clearLabel ? [{ value: "", label: clearLabel, clear: true }, ...options] : options;
    if (!q) return base;
    return options.filter((o) => `${o.label} ${o.hint || ""} ${o.search || ""}`.toLowerCase().includes(q));
  }, [options, query, clearLabel]);

  useEffect(() => {
    if (!open) return undefined;
    searchRef.current?.focus();
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  useEffect(() => {
    listRef.current?.querySelector(".search-select-option.active")?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function choose(option) {
    onChange(option.value);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      // Never let Enter here submit the order form this sits inside.
      e.preventDefault();
      if (matches[active]) choose(matches[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div className={`search-select${open ? " open" : ""}`} ref={rootRef}>
      <button
        type="button"
        id={id}
        className="form-control search-select-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={selected ? "" : "search-select-placeholder"}>{selected ? selected.label : placeholder}</span>
        <span className="search-select-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div className="search-select-panel">
          <input
            ref={searchRef}
            type="text"
            className="form-control search-select-search"
            placeholder={searchPlaceholder || "Search..."}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label={searchPlaceholder || "Search"}
          />
          <ul className="search-select-list" role="listbox" ref={listRef}>
            {matches.length === 0 && <li className="search-select-empty">{emptyText || "No matches found."}</li>}
            {matches.map((o, i) => (
              <li
                key={o.clear ? "__clear" : o.value}
                role="option"
                aria-selected={String(o.value) === String(value)}
                className={`search-select-option${i === active ? " active" : ""}${String(o.value) === String(value) ? " selected" : ""}${o.clear ? " clear" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(o)}
              >
                <span>{o.label}</span>
                {o.hint && <span className="search-select-hint">{o.hint}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
