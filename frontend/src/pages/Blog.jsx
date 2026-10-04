import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Blog() {
  const [posts, setPosts] = useState(null);
  useDocumentTitle("Blog & Updates | Aaiji Nursery");

  useEffect(() => {
    api.get("/blog").then(setPosts);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Blog & Updates</h1>
          <p>Growing tips, seasonal advice, offers and nursery news.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!posts ? (
            <Loading />
          ) : posts.length === 0 ? (
            <Empty>No blog posts yet.</Empty>
          ) : (
            <div className="grid grid-3">
              {posts.map((post) => (
                <Link key={post.id} to={`/blog/${post.slug}`} className="card">
                  <img src={post.image_url} alt={post.title} loading="lazy" />
                  <div className="card-body">
                    <span style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
                      {new Date(post.published_at).toLocaleDateString()}
                    </span>
                    <h3 style={{ fontSize: "1.05rem", margin: "6px 0" }}>{post.title}</h3>
                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
                      {post.excerpt}
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
