import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main-content">
      <section className="state" aria-labelledby="not-found-title">
        <p className="state-code" aria-hidden="true">
          404
        </p>
        <h1 id="not-found-title" className="section-title">
          This page could not be found
        </h1>
        <p className="lead">The link may be broken, or the page may have moved.</p>
        <Link className="btn btn-primary" href="/">
          Back to the home page
        </Link>
      </section>
    </main>
  );
}
