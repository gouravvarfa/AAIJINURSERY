import CrudPage from "../CrudPage";

export default function Purchases() {
  return (
    <CrudPage
      title="Purchases"
      resource="/admin/purchases"
      idKey="id"
      allowEdit={false}
      idempotent
      deleteConfirmMessage={(p) =>
        `Delete this purchase from ${p.supplier || "this supplier"} (₹${p.total_cost.toLocaleString()})? ` +
        `The stock it already added will NOT be reversed automatically -- adjust it manually on the Plants page if needed.`
      }
      columns={[
        {
          key: "purchase_date",
          label: "Date",
          render: (p) => new Date(p.purchase_date).toLocaleDateString(),
        },
        { key: "supplier", label: "Supplier", render: (p) => p.supplier || "-" },
        { key: "items", label: "Items", render: (p) => `${p.items.length} plant(s)` },
        {
          key: "total_cost",
          label: "Total Cost",
          render: (p) => `₹${p.total_cost.toLocaleString()}`,
        },
      ]}
      fields={[
        { name: "purchase_date", label: "Purchase Date", type: "date", required: true },
        { name: "supplier_contact_id", label: "Supplier (optional)", type: "supplier_select" },
        { name: "invoice_number", label: "Invoice Number (optional)", type: "text" },
        { name: "items", label: "Plants Purchased", type: "purchase_items", required: true },
        { name: "notes", label: "Notes (optional)", type: "textarea" },
      ]}
    />
  );
}
