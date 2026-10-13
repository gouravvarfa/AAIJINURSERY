import { useEffect, useMemo, useState } from "react";
import { api } from "../../../api";

export default function SendMessage() {
  const [customers, setCustomers] = useState([]);
  const [customerQuery, setCustomerQuery] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [manualMobile, setManualMobile] = useState("");
  const [manualName, setManualName] = useState("");

  const [templates, setTemplates] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [params, setParams] = useState([]);

  const [result, setResult] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const [sending, setSending] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api.get("/admin/customers").then(setCustomers).catch(() => {});
    api.get("/admin/communications/templates").then((rows) => setTemplates(rows.filter((t) => t.status === "ACTIVE"))).catch(() => {});
  }, []);

  const filteredCustomers = useMemo(() => {
    if (!customerQuery) return [];
    const q = customerQuery.toLowerCase();
    return customers.filter((c) => c.name.toLowerCase().includes(q) || (c.mobile || "").includes(q)).slice(0, 20);
  }, [customers, customerQuery]);

  const activeTemplate = templates.find((t) => t.name === templateName);

  function pickCustomer(c) {
    setSelectedCustomer(c);
    setCustomerQuery(`${c.name} (${c.id})`);
    setManualMobile("");
    setManualName("");
  }

  function selectTemplate(name) {
    setTemplateName(name);
    const t = templates.find((tt) => tt.name === name);
    setParams(t ? t.variables.map(() => "") : []);
    setResult(null);
  }

  const mobile = selectedCustomer ? selectedCustomer.mobile : manualMobile;
  const customerName = selectedCustomer ? selectedCustomer.name : manualName;

  const preview = useMemo(() => {
    if (!activeTemplate) return "";
    let text = activeTemplate.preview || "";
    activeTemplate.variables.forEach((varName, i) => {
      text = text.replaceAll(`{{${varName}}}`, params[i] || `{{${varName}}}`);
    });
    return text;
  }, [activeTemplate, params]);

  async function handleSend(isTest) {
    setResult(null);
    setTestResult(null);
    if (!mobile) return;
    if (!templateName) return;
    if (isTest) {
      setTesting(true);
      try {
        const r = await api.post("/admin/communications/test", { mobile, template_name: templateName, template_params: params });
        setTestResult(r);
      } finally {
        setTesting(false);
      }
    } else {
      setSending(true);
      try {
        const r = await api.post("/admin/communications/send", {
          customer_id: selectedCustomer?.id,
          mobile, customer_name: customerName || "Customer",
          template_name: templateName, template_params: params,
        });
        setResult(r);
      } finally {
        setSending(false);
      }
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Send WhatsApp Message</h1>
      </div>

      <div className="admin-form-card" style={{ maxWidth: 640 }}>
        <div className="form-group">
          <label>Customer</label>
          <input
            type="text"
            className="form-control"
            placeholder="Search customer by name or mobile..."
            value={customerQuery}
            onChange={(e) => {
              setCustomerQuery(e.target.value);
              setSelectedCustomer(null);
            }}
          />
          {customerQuery && !selectedCustomer && filteredCustomers.length > 0 && (
            <div className="admin-table-wrap" style={{ marginTop: 6, maxHeight: 200, overflowY: "auto" }}>
              <table className="admin-table">
                <tbody>
                  {filteredCustomers.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => pickCustomer(c)}>
                      <td>{c.name}</td>
                      <td>{c.mobile || "-"}</td>
                      <td>{c.order_count} order(s)</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <small style={{ color: "var(--color-text-muted)" }}>Only customers with at least one order appear here. Or enter a mobile number manually below.</small>
        </div>

        {!selectedCustomer && (
          <>
            <div className="form-group">
              <label>Or Mobile Number</label>
              <input type="text" className="form-control" placeholder="9876543210" value={manualMobile} onChange={(e) => setManualMobile(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Customer Name (for the message)</label>
              <input type="text" className="form-control" value={manualName} onChange={(e) => setManualName(e.target.value)} />
            </div>
          </>
        )}

        <div className="form-group">
          <label>Template</label>
          <select className="form-control" value={templateName} onChange={(e) => selectTemplate(e.target.value)}>
            <option value="">Select an active template...</option>
            {templates.map((t) => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
          </select>
          {templates.length === 0 && (
            <small style={{ color: "var(--color-text-muted)" }}>
              No active templates yet -- activate one in Communications &gt; Templates once it's approved in AiSensy.
            </small>
          )}
        </div>

        {activeTemplate && activeTemplate.variables.map((varName, i) => (
          <div className="form-group" key={varName}>
            <label>{varName}</label>
            <input
              type="text"
              className="form-control"
              value={params[i] || ""}
              onChange={(e) => setParams((prev) => prev.map((p, idx) => (idx === i ? e.target.value : p)))}
            />
          </div>
        ))}

        {activeTemplate && (
          <div className="form-group">
            <label>Preview</label>
            <div style={{ background: "var(--color-bg-soft, #f6f7f5)", border: "1px solid var(--color-border)", borderRadius: 8, padding: 12, whiteSpace: "pre-wrap", fontSize: "0.88rem" }}>
              {preview}
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-outline dark" disabled={!mobile || !templateName || testing} onClick={() => handleSend(true)}>
            {testing ? "Sending Test..." : "Send Test"}
          </button>
          <button className="btn btn-primary" disabled={!mobile || !templateName || sending} onClick={() => handleSend(false)}>
            {sending ? "Sending..." : "Send WhatsApp"}
          </button>
        </div>

        {testResult && (
          <div className={`alert ${testResult.success ? "alert-success" : "alert-error"}`} style={{ marginTop: 16 }}>
            {testResult.success ? "Test message accepted by AiSensy." : `Failed: ${testResult.error_code} -- ${testResult.error_message}`}
          </div>
        )}
        {result && (
          <div className={`alert ${result.success ? "alert-success" : "alert-error"}`} style={{ marginTop: 16 }}>
            {result.success ? `Queued (message #${result.message_id}). Check Message History for delivery status.` : `Not sent: ${result.reason}`}
          </div>
        )}
      </div>
    </div>
  );
}
