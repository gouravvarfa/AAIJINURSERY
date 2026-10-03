import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import PlantCard from "../components/PlantCard";
import { Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

// Mirrors app/api_public.py's PLANT_SORT_OPTIONS -- these are the only sort
// orders the backend actually supports, same list PlantExplorer.jsx already
// uses for the homepage explorer (no new/fake sort behavior introduced).
const SORT_OPTIONS = [
  { value: "", label: "Default" },
  { value: "newest", label: "Newest First" },
  { value: "price_asc", label: "Price: Low to High" },
  { value: "price_desc", label: "Price: High to Low" },
  { value: "name", label: "Name: A to Z" },
];

function PlantCardSkeleton() {
  return (
    <div className="card plant-card plant-card-skeleton" aria-hidden="true">
      <div className="skeleton skeleton-image" />
      <div className="card-body">
        <div className="skeleton skeleton-line" style={{ width: "40%" }} />
        <div className="skeleton skeleton-line" style={{ width: "75%", height: 18 }} />
        <div className="skeleton skeleton-line" style={{ width: "95%" }} />
        <div className="skeleton skeleton-line" style={{ width: "35%", height: 20 }} />
      </div>
      <div className="card-actions">
        <div className="skeleton skeleton-button" />
      </div>
    </div>
  );
}

export default function Plants() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeCategory = searchParams.get("category") || "";
  const activeSearch = searchParams.get("search") || "";
  const activeSort = searchParams.get("sort_by") || "";
  useDocumentTitle("Our Plant Catalog | Aaiji Nursery");
  const [categories, setCategories] = useState(null);
  const [allPlants, setAllPlants] = useState(null); // unfiltered, active only -- real counts per category
  const [plants, setPlants] = useState(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    api.get("/categories").then(setCategories).catch(() => setCategories([]));
    api
      .get("/plants")
      .then(setAllPlants)
      .catch(() => setAllPlants([]));
  }, []);

  function load() {
    setPlants(null);
    setLoadError(false);
    const params = new URLSearchParams();
    if (activeCategory) params.set("category", activeCategory);
    if (activeSearch) params.set("search", activeSearch);
    if (activeSort) params.set("sort_by", activeSort);
    const query = params.toString() ? `?${params.toString()}` : "";
    api
      .get(`/plants${query}`)
      .then(setPlants)
      .catch(() => setLoadError(true));
  }

  useEffect(load, [activeCategory, activeSearch, activeSort]);

  function selectCategory(slug) {
    const next = new URLSearchParams(searchParams);
    if (slug) next.set("category", slug);
    else next.delete("category");
    setSearchParams(next);
  }

  function setSort(value) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set("sort_by", value);
    else next.delete("sort_by");
    setSearchParams(next);
  }

  function clearFilters() {
    setSearchParams({});
  }

  const categoryCount = (slug) =>
    allPlants ? allPlants.filter((p) => p.category?.slug === slug).length : null;

  return (
    <>
      <section className="page-hero plants-hero">
        <div className="container">
          <h1>Plants</h1>
          <p>Healthy plants for a greener tomorrow.</p>
        </div>
      </section>

      <section className="section plants-section">
        <div className="container">
          {activeSearch && (
            <div className="filter-chips">
              <button
                type="button"
                className="chip"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.delete("search");
                  setSearchParams(next);
                }}
              >
                Search: "{activeSearch}" <span aria-hidden="true">&times;</span>
              </button>
            </div>
          )}

          <div className="plants-controls">
            <div className="category-pills">
              <button
                className={`pill ${!activeCategory ? "active" : ""}`}
                onClick={() => selectCategory("")}
              >
                All Plants {allPlants && <span className="pill-count">{allPlants.length}</span>}
              </button>
              {categories?.map((cat) => (
                <button
                  key={cat.id}
                  className={`pill ${activeCategory === cat.slug ? "active" : ""}`}
                  onClick={() => selectCategory(cat.slug)}
                >
                  {cat.name}{" "}
                  {categoryCount(cat.slug) !== null && (
                    <span className="pill-count">{categoryCount(cat.slug)}</span>
                  )}
                </button>
              ))}
            </div>

            <select
              className="form-control plants-sort-select"
              value={activeSort}
              onChange={(e) => setSort(e.target.value)}
              aria-label="Sort by"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  Sort by: {opt.label}
                </option>
              ))}
            </select>
          </div>

          {loadError ? (
            <Empty>
              <p style={{ fontWeight: 600, color: "var(--color-text)" }}>Unable to load plants</p>
              <p style={{ color: "var(--color-text-muted)" }}>Please try again.</p>
              <button type="button" className="btn btn-primary btn-sm" style={{ marginTop: 12 }} onClick={load}>
                Try Again
              </button>
            </Empty>
          ) : !plants ? (
            <div className="grid grid-4 grid-plants">
              {Array.from({ length: 8 }).map((_, i) => (
                <PlantCardSkeleton key={i} />
              ))}
            </div>
          ) : plants.length === 0 ? (
            <Empty>
              <p>
                {activeSearch
                  ? `No plants found for "${activeSearch}".`
                  : "No plants found. Try changing your filters or search."}
              </p>
              {(activeCategory || activeSearch || activeSort) && (
                <button type="button" className="btn btn-outline dark btn-sm" style={{ marginTop: 12 }} onClick={clearFilters}>
                  Clear Filters
                </button>
              )}
            </Empty>
          ) : (
            <div className="grid grid-4 grid-plants">
              {plants.map((plant) => (
                <PlantCard key={plant.id} plant={plant} />
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
