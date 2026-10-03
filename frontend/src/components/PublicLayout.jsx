import { Outlet } from "react-router-dom";
import Navbar from "./Navbar";
import Footer from "./Footer";
import WhatsAppButton from "./WhatsAppButton";
import BottomNav from "./BottomNav";
import Toast from "./Toast";

export default function PublicLayout() {
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
