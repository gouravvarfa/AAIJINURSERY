// Run: node --test frontend/tests   (Node's built-in runner, no extra packages)
import test from "node:test";
import assert from "node:assert/strict";
import { deliveryAlert, istToday, formatDeliveryDate, matchesDeliveryFilter, dateOnly } from "../src/admin/accounting/deliveryAlert.js";

const TODAY = "2026-10-13";
const at = (deliveryDate, extra = {}) => deliveryAlert({ deliveryDate, ...extra }, TODAY);

test("due today is red", () => assert.deepEqual([at("2026-10-13T00:00:00").level, at("2026-10-13T00:00:00").kind], ["red", "today"]));
test("due tomorrow is orange", () => assert.deepEqual([at("2026-10-14T00:00:00").level, at("2026-10-14T00:00:00").kind], ["orange", "tomorrow"]));
test("2 and 3 days are orange 'soon'", () => {
  assert.equal(at("2026-10-15").kind, "soon");
  assert.equal(at("2026-10-16").kind, "soon");
  assert.equal(at("2026-10-16").level, "orange");
});
test("4+ days is green", () => assert.deepEqual([at("2026-10-17").level, at("2026-10-17").days], ["green", 4]));
test("past date is overdue with day count", () => {
  const a = at("2026-10-11T00:00:00");
  assert.deepEqual([a.level, a.kind, a.label], ["red", "overdue", "Overdue 2d"]);
});
test("delivered / partially delivered / cancelled delivery: no alert", () => {
  for (const s of ["Delivered", "Partially Delivered", "Cancelled"]) assert.equal(at("2026-10-13", { deliveryStatus: s }), null);
});
test("failed delivery still alerts", () => assert.equal(at("2026-10-12", { deliveryStatus: "Failed" }).kind, "overdue"));
test("cancelled / voided document: no alert", () => {
  assert.equal(at("2026-10-13", { status: "Cancelled" }), null);
  assert.equal(at("2026-10-13", { status: "Voided" }), null);
});
test("missing date: no alert", () => {
  for (const v of [null, undefined, "", "garbage"]) assert.equal(at(v), null);
});
test("month and year boundaries are calendar days", () => {
  assert.equal(deliveryAlert({ deliveryDate: "2026-11-01" }, "2026-10-31").kind, "tomorrow");
  assert.equal(deliveryAlert({ deliveryDate: "2027-01-01" }, "2026-12-31").kind, "tomorrow");
  assert.equal(deliveryAlert({ deliveryDate: "2026-03-01" }, "2026-02-28").kind, "tomorrow");
  assert.equal(deliveryAlert({ deliveryDate: "2028-02-29" }, "2028-02-28").kind, "tomorrow");
});
test("'today' is the India date even when UTC is still the previous day", () => {
  // 2026-10-13 00:30 IST == 2026-10-12 19:00 UTC
  assert.equal(istToday(new Date("2026-10-12T19:00:00Z")), "2026-10-13");
  // 2026-10-13 23:59 IST == 2026-10-13 18:29 UTC
  assert.equal(istToday(new Date("2026-10-13T18:29:00Z")), "2026-10-13");
  // 2026-10-14 00:00 IST == 2026-10-13 18:30 UTC
  assert.equal(istToday(new Date("2026-10-13T18:30:00Z")), "2026-10-14");
});
test("result does not depend on the machine time zone", () => {
  for (const tz of ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Pacific/Auckland"]) {
    process.env.TZ = tz;
    assert.equal(deliveryAlert({ deliveryDate: "2026-10-14T00:00:00" }, "2026-10-13").kind, "tomorrow");
    assert.equal(formatDeliveryDate("2026-10-15T00:00:00"), "15 Oct 2026");
  }
});
test("date formatting + dateOnly", () => {
  assert.equal(formatDeliveryDate("2026-10-05T00:00:00"), "5 Oct 2026");
  assert.equal(formatDeliveryDate(null), "");
  assert.equal(dateOnly("2026-10-05T00:00:00"), "2026-10-05");
});
test("filters", () => {
  const info = (d) => at(d);
  assert.ok(matchesDeliveryFilter(info("2026-10-11"), "overdue"));
  assert.ok(matchesDeliveryFilter(info("2026-10-13"), "today"));
  assert.ok(matchesDeliveryFilter(info("2026-10-14"), "tomorrow"));
  assert.ok(matchesDeliveryFilter(info("2026-10-13"), "soon") && matchesDeliveryFilter(info("2026-10-16"), "soon"));
  assert.ok(!matchesDeliveryFilter(info("2026-10-17"), "soon") && matchesDeliveryFilter(info("2026-10-17"), "later"));
  assert.ok(matchesDeliveryFilter(null, "none") && !matchesDeliveryFilter(info("2026-10-14"), "none"));
  assert.ok(matchesDeliveryFilter(null, "") && matchesDeliveryFilter(info("2026-10-14"), ""));
  assert.ok(!matchesDeliveryFilter(null, "overdue"));
});
