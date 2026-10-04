import { useEffect, useState } from "react";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Gallery() {
  const [images, setImages] = useState(null);
  useDocumentTitle("Gallery | Aaiji Nursery");

  useEffect(() => {
    api.get("/gallery").then(setImages);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Gallery</h1>
          <p>A look inside our nursery, our plants and our work.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!images ? (
            <Loading />
          ) : images.length === 0 ? (
            <Empty>No gallery images added yet.</Empty>
          ) : (
            <div className="gallery-grid">
              {images.map((img) => (
                <figure key={img.id}>
                  <img src={img.image_url} alt={img.caption} loading="lazy" />
                  {img.caption && <figcaption>{img.caption}</figcaption>}
                </figure>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
