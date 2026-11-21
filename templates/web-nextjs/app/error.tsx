"use client";

import { useEffect } from "react";

/** Route-level error boundary: shows a friendly message and lets the visitor retry. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main id="main-content">
      <section className="state" role="alert" aria-labelledby="error-title">
        <p className="state-code" aria-hidden="true">
          Oops
        </p>
        <h1 id="error-title" className="section-title">
          Something went wrong
        </h1>
        <p className="lead">An unexpected error occurred. You can try again; if it keeps happening, please let us know.</p>
        <button type="button" className="btn btn-primary" onClick={() => reset()}>
          Try again
        </button>
      </section>
    </main>
  );
}
