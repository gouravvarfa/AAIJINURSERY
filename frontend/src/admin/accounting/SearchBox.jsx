import { useState } from "react";

// Debounced-on-submit search input, reused across every Accounting list page
// (Sales Orders, Invoices, Purchase Orders, Bills, Expenses, Contacts).
export default function SearchBox({ value, onChange, placeholder = "Search..." }) {
  const [draft, setDraft] = useState(value || "");

  function submit(e) {
    e?.preventDefault();
    onChange(draft);
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        type="text"
        className="form-control admin-control-sm"
        style={{ maxWidth: 260 }}
        placeholder={placeholder}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <button type="submit" className="btn btn-sm btn-outline dark">
        Search
      </button>
      {value && (
        <button
          type="button"
          className="btn btn-sm btn-outline dark"
          onClick={() => {
            setDraft("");
            onChange("");
          }}
        >
          Clear
        </button>
      )}
    </form>
  );
}
