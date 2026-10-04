import { useEffect, useState } from "react";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function FAQs() {
  const [faqs, setFaqs] = useState(null);
  const [openId, setOpenId] = useState(null);
  useDocumentTitle("FAQs | Aaiji Nursery");

  useEffect(() => {
    api.get("/faqs").then(setFaqs);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Frequently Asked Questions</h1>
          <p>Quick answers about our plants, orders, delivery and care.</p>
        </div>
      </section>

      <section className="section">
        <div className="container" style={{ maxWidth: 760 }}>
          {!faqs ? (
            <Loading />
          ) : faqs.length === 0 ? (
            <Empty>No FAQs added yet.</Empty>
          ) : (
            faqs.map((faq) => (
              <div key={faq.id} className={`faq-item ${openId === faq.id ? "open" : ""}`}>
                <button
                  className="faq-question"
                  onClick={() => setOpenId(openId === faq.id ? null : faq.id)}
                >
                  {faq.question}
                  <span className="faq-icon">+</span>
                </button>
                <div className="faq-answer">
                  <p>{faq.answer}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </>
  );
}
