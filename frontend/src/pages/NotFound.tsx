import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 pb-16 pt-32">
      <p className="text-accent">404</p>
      <h1 className="font-serif text-3xl">Page not found</h1>
      <p className="text-muted">
        Check the link, look up a product ID, or return to the dashboard.
      </p>
      <div className="flex flex-wrap gap-5 text-accent underline">
        <Link to="/verify">Verify a product</Link>
        <Link to="/">Dashboard</Link>
        <Link to="/demo">Guided demo</Link>
      </div>
    </div>
  );
}
