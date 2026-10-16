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
    <div>
      <div className="admin-page-head"><h1>Customer Seeds</h1></div>
      <SeedEntries plants={plants} startOpen={params.get("new") === "1"} />
    </div>
  );
}
