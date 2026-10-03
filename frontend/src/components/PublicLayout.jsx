import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { api } from "../api";
import Navbar from "./Navbar";
import Footer from "./Footer";
import WhatsAppButton from "./WhatsAppButton";
import BottomNav from "./BottomNav";
import Toast from "./Toast";

// The backend dedups by session cookie regardless (one row per browser
// session, see POST /api/track-visit), but this sessionStorage flag avoids
// even making the request again on every client-side route change within
// the same tab -- a plain visit counter, not a full pageview/analytics
// system, so once per tab is all this needs.
const VISIT_FLAG = "aaiji_visit_tracked";

export default function PublicLayout() {
  useEffect(() => {
    if (sessionStorage.getItem(VISIT_FLAG)) return;
    sessionStorage.setItem(VISIT_FLAG, "1");
    api.post("/track-visit").catch(() => {});
  }, []);

  return (
    <>
      <Navbar />
      <main className="has-bottom-nav">
        <Outlet />
      </main>
      <Footer />
      <WhatsAppButton />
      <BottomNav />
      <Toast />
    </>
  );
}
