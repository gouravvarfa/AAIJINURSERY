import { useSettings } from "../context/SettingsContext";
import whatsappIcon from "../assets/whatsapp-icon.png";

export default function WhatsAppButton() {
  const settings = useSettings();
  const number = settings.whatsapp;
  if (!number) return null;

  return (
    <a
      className="whatsapp-fab"
      href={`https://wa.me/${number}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat on WhatsApp"
      title="Chat on WhatsApp"
    >
      <img src={whatsappIcon} alt="" />
    </a>
  );
}
