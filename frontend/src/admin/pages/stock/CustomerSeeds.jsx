import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import SeedEntries from "./SeedEntries";

// Customer Seeds: seeds customers gave us, and what came out of them. One page, no stock maths changed.
export default function CustomerSeeds() {
  const [params] = useSearchParams();
  const [plants, setPlants] = useState([]);
  useEffect(() => { api.get("/admin/plants").then(setPlants).catch(() => {}); }, []);
  return (
    <div className="sm seeds-page">
      <div className="sm-head">
        <div className="sm-title">
          <span className="sm-title-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3c3 3 5 6 5 9a5 5 0 0 1-10 0c0-3 2-6 5-9z" /></svg>
          </span>
          <div>
            <h1>Customer Seeds</h1>
            <p>Seeds given by customers, and how many plants came out good, extra or bad.</p>
          </div>
        </div>
      </div>
      <SeedEntries plants={plants} startOpen={params.get("new") === "1"} />
    </div>
  );
}
