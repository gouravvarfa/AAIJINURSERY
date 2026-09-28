import { useEffect, useState } from "react";
import { api } from "../../api";
import CrudPage from "../CrudPage";
import { Loading } from "../../components/Loading";

const columns = [
  { key: "name", label: "Name" },
  {
    key: "variants",
    label: "Type",
    render: (item) =>
      item.variants && item.variants.length > 0 ? (
        <span className="badge badge-accent">
          Tray ({item.variants.length} size{item.variants.length > 1 ? "s" : ""})
        </span>
      ) : (
        <span className="badge badge-muted">Normal</span>
      ),
  },
  {
    key: "image_url",
    label: "Image",
    render: (item) => (item.image_url ? <img className="thumb" src={item.image_url} alt="" /> : "-"),
  },
  { key: "price", label: "Price", render: (item) => `₹${item.price}` },
  { key: "stock_quantity", label: "Stock" },
  {
    key: "availability_status",
    label: "Availability",
    render: (item) => {
      const map = {
        AVAILABLE: "badge-accent",
        OUT_OF_STOCK: "badge-muted",
        ENQUIRY_AVAILABLE: "badge-gold",
      };
      return <span className={`badge ${map[item.availability_status] || "badge-muted"}`}>{item.availability_status}</span>;
    },
  },
  { key: "is_active", label: "Active", render: (item) => (item.is_active ? "Yes" : "No") },
];

export default function Plants() {
  const [categories, setCategories] = useState(null);

  useEffect(() => {
    api.get("/admin/categories").then(setCategories);
  }, []);

  if (!categories) return <Loading />;

  const fields = [
    { name: "name", label: "Name", required: true },
    {
      name: "category_id",
      label: "Category",
      type: "select",
      required: true,
      options: categories.map((c) => ({ value: c.id, label: c.name })),
    },
    { name: "description", label: "Description", type: "textarea" },
    {
      name: "price",
      label: "Price per Unit / Seed (₹)",
      type: "number",
      required: true,
      help: "If you add Tray/Pack Options below, each tray's selling price is this × the tray size (calculated automatically -- you don't set tray prices separately).",
    },
    { name: "discount_price", label: "Discount Price (₹, optional)", type: "number" },
    {
      name: "stock_quantity",
      label: "Stock Quantity (single-unit sale only)",
      type: "number",
      help: "Only matters if you leave Tray/Pack Options empty below. As soon as you add at least one tray option, stock is tracked per tray size there instead, and this field is ignored.",
    },
    { name: "sku", label: "SKU" },
    { name: "image_url", label: "Image URL", placeholder: "https://..." },
    { name: "care_level", label: "Care Level", placeholder: "Easy / Moderate / Advanced", default: "Easy" },
    {
      name: "features",
      label: "Features",
      type: "textarea",
      help: "One feature per line",
    },
    { name: "is_featured", label: "Featured", type: "checkbox", checkboxLabel: "Show on homepage" },
    { name: "is_active", label: "Active", type: "checkbox", checkboxLabel: "Visible on site", default: true },
    {
      name: "availability_status",
      label: "Availability",
      type: "select",
      default: "AVAILABLE",
      help: "ENQUIRY_AVAILABLE shows an \"Enquire Now\" button instead of Add to Cart/Buy Now -- for plants you can prepare on request even though they're currently out of stock.",
      options: [
        { value: "AVAILABLE", label: "Available (normal purchase)" },
        { value: "OUT_OF_STOCK", label: "Out of Stock (no purchase, no enquiry)" },
        { value: "ENQUIRY_AVAILABLE", label: "Enquiry Available (customer can Enquire Now)" },
      ],
    },
    {
      name: "variants",
      label: "Tray / Pack Options (recommended for every plant)",
      type: "variants",
      default: [],
      help: "Add one row per pack/tray size customers can buy (e.g. a tray of 150 seeds). Each tray's price is calculated automatically from Price per Unit above, and its stock is tracked separately per size -- once you add even one row here, customers must pick a tray size to buy, and the plain Stock Quantity field above is ignored.",
    },
  ];

  return <CrudPage title="Plant" resource="/admin/plants" fields={fields} columns={columns} />;
}
