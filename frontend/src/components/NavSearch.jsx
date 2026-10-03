import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

const SUGGESTION_LIMIT = 5;
const DEBOUNCE_MS = 350;

export default function NavSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef(null);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    function handleEscape(e) {
      if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .getPaged(`/plants?search=${encodeURIComponent(trimmed)}&limit=${SUGGESTION_LIMIT}`)
        .then((data) => setSuggestions(data.items))
        .finally(() => setLoading(false));
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  function closeAndReset() {
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  }

  function goToAllResults() {
    const trimmed = query.trim();
    if (!trimmed) return;
    closeAndReset();
    navigate(`/plants?search=${encodeURIComponent(trimmed)}`);
  }

  function selectPlant(slug) {
    closeAndReset();
    navigate(`/plants/${slug}`);
  }

  const showDropdown = open && query.trim().length > 0;

  return (
    <div className={`nav-search ${open ? "open" : ""}`} ref={containerRef}>
      <form
        className="nav-search-bar"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          goToAllResults();
        }}
      >
        <button
          type="button"
          className="nav-search-icon"
          aria-label="Search"
          onClick={() => inputRef.current?.focus()}
        >
          &#128269;
        </button>
        <input
          ref={inputRef}
          id="nav-search-input"
          type="search"
          className="nav-search-input"
          placeholder="Search plants, products..."
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          aria-label="Search plants"
        />
        {query && (
          <button
            type="button"
            className="nav-search-clear"
            aria-label="Clear search"
            onClick={() => {
              setQuery("");
              inputRef.current?.focus();
            }}
          >
            &times;
          </button>
        )}
      </form>

      {showDropdown && (
        <div className="nav-search-dropdown">
          {loading ? (
            <div className="nav-search-status">Searching...</div>
          ) : suggestions.length === 0 ? (
            <div className="nav-search-status">No plants found for "{query.trim()}"</div>
          ) : (
            <>
              {suggestions.map((plant) => (
                <button
                  type="button"
                  key={plant.id}
                  className="nav-search-item"
                  onClick={() => selectPlant(plant.slug)}
                >
                  <img src={plant.image_url} alt="" />
                  <span className="nav-search-item-info">
                    <strong>{plant.name}</strong>
                    <span className="nav-search-item-price">&#8377;{plant.effective_price}</span>
                  </span>
                </button>
              ))}
              <button type="button" className="nav-search-viewall" onClick={goToAllResults}>
                View all results for "{query.trim()}" &rarr;
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
