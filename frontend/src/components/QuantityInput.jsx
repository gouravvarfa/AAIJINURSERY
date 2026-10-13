import { useEffect, useRef, useState } from "react";
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
  max = MAX_ORDER_QUANTITY,
}) {
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

  return (
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
}
