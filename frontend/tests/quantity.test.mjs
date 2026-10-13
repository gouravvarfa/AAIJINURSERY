import test from "node:test";
import assert from "node:assert/strict";
import { MAX_ORDER_QUANTITY, parseQuantity, sanitizeQuantityText, stepQuantity, stockNote } from "../src/utils/quantity.js";

test("typed / pasted text becomes a whole number", () => {
  assert.equal(parseQuantity("250"), 250);
  assert.equal(parseQuantity("1,000"), 1000);
  assert.equal(parseQuantity(" 5 000 "), 5000);
  assert.equal(parseQuantity("250 plants"), 250);
  assert.equal(parseQuantity("-3"), 3); // the minus sign is dropped, never a negative quantity
});
test("empty, zero and unsafe values are rejected", () => {
  for (const v of ["", "   ", "abc", "0", "000", null, undefined]) assert.equal(parseQuantity(v), null);
  assert.equal(parseQuantity(String(MAX_ORDER_QUANTITY + 1)), null);
  assert.equal(parseQuantity("99999999999999999999"), null);
});
test("bulk quantities above any stock are allowed", () => {
  assert.equal(parseQuantity("5000"), 5000);
  assert.equal(parseQuantity(String(MAX_ORDER_QUANTITY)), MAX_ORDER_QUANTITY);
});
test("plus / minus never go below 1 or above the maximum", () => {
  assert.equal(stepQuantity(1, -1), 1);
  assert.equal(stepQuantity(5, 1), 6);
  assert.equal(stepQuantity(MAX_ORDER_QUANTITY, 1), MAX_ORDER_QUANTITY);
  assert.equal(stepQuantity("abc", 1), 2);
});
test("typing then +/- works together", () => {
  const typed = parseQuantity("250");
  assert.equal(stepQuantity(typed, 1), 251);
  assert.equal(stepQuantity(stepQuantity(typed, 1), -1), 250);
});
test("sanitize caps the length", () => assert.equal(sanitizeQuantityText("123456789012"), "1234567"));
test("stock note never blocks and never over-promises", () => {
  assert.equal(stockNote(1000, 400), "In stock");
  assert.match(stockNote(500, 2000), /500 in stock now\. The remaining 1,500 will be prepared.*delivery date/);
  assert.match(stockNote(0, 300), /Made to order/);
});
