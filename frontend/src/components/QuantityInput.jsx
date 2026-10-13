import { useEffect, useId, useRef, useState } from "react";
import { MAX_ORDER_QUANTITY, parseQuantity, sanitizeQuantityText, stepQuantity } from "../utils/quantity";

// Minus / number box / plus. The number can be typed or pasted, and the
// buttons keep working. Never limited by stock (see utils/quantity.js).
//
// `commitOnBlur`: for controls that save to the server (the cart) -- typing
// only updates the box, and the new quantity is sent once when the customer
// leaves the box or presses Enter, instead of on every keystroke. The +/-
// buttons always commit immediately.
export default function QuantityInput({
  value,
  onChange,
  label = "Quantity",
  disabled = false,
  commitOnBlur = false,
  directEntry = false,
  max = MAX_ORDER_QUANTITY,
}) {
  const directId = useId();
  const [direct, setDirect] = useState("");
  const [directError, setDirectError] = useState("");
  const [text, setText] = useState(String(value));
  const [invalid, setInvalid] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    setText(String(value));
    setInvalid(false);
  }, [value]);

  function handleType(e) {
    const next = sanitizeQuantityText(e.target.value, max);
    setText(next);
    const n = parseQuantity(next, max);
    setInvalid(next !== "" && n === null);
    if (n !== null && !commitOnBlur && n !== value) onChange(n);
  }

  function commit() {
    const n = parseQuantity(text, max);
    if (n === null) {
      // empty / 0 / invalid: go back to the last good quantity
      setText(String(value));
      setInvalid(false);
      return;
    }
    setText(String(n));
    if (n !== value) onChange(n);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
      inputRef.current?.blur();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      onChange(stepQuantity(value, 1, max));
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      onChange(stepQuantity(value, -1, max));
    }
  }

  // A second, clearly labelled box next to the +/- control for typing the
  // quantity straight in. Both stay in sync (they set the same value).
  function applyDirect() {
    if (direct === "") return;
    const n = parseQuantity(direct, max);
    if (n === null) {
      setDirectError(`Enter a whole number from 1 to ${max.toLocaleString("en-IN")}`);
      return;
    }
    setDirectError("");
    setDirect("");
    if (n !== value) onChange(n);
  }

  const stepper = (
    <div className="cart-row-qty qty-input-group">
      <button
        type="button"
        className="qty-btn"
        onClick={() => onChange(stepQuantity(value, -1, max))}
        disabled={disabled || value <= 1}
        aria-label={`Decrease ${label.toLowerCase()}`}
      >
        &minus;
      </button>
      <input
        ref={inputRef}
        className={`qty-input${invalid ? " qty-input-invalid" : ""}`}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        value={text}
        disabled={disabled}
        onChange={handleType}
        onBlur={commit}
        onKeyDown={handleKeyDown}
        onFocus={(e) => e.target.select()}
        aria-label={label}
        aria-invalid={invalid}
        size={Math.max(3, text.length)}
      />
      <button
        type="button"
        className="qty-btn"
        onClick={() => onChange(stepQuantity(value, 1, max))}
        disabled={disabled || value >= max}
        aria-label={`Increase ${label.toLowerCase()}`}
      >
        +
      </button>
    </div>
  );

  if (!directEntry) return stepper;

  return (
    <div className="qty-with-direct">
      {stepper}
      <div className="qty-direct">
        <label className="qty-direct-label" htmlFor={directId}>
          Or type {label.toLowerCase()}
        </label>
        <div className="qty-direct-row">
          <input
            id={directId}
            className={`qty-direct-input${directError ? " qty-input-invalid" : ""}`}
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="off"
            placeholder="e.g. 500"
            value={direct}
            disabled={disabled}
            onChange={(e) => {
              setDirect(sanitizeQuantityText(e.target.value, max));
              setDirectError("");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                applyDirect();
              }
            }}
            aria-invalid={!!directError}
          />
          <button type="button" className="btn btn-sm btn-outline dark qty-direct-set" onClick={applyDirect} disabled={disabled || direct === ""}>
            Set
          </button>
        </div>
        {directError && <div className="qty-direct-error" role="alert">{directError}</div>}
      </div>
    </div>
  );
}
