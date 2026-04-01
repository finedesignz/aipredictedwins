"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      if (res.ok) {
        router.push("/");
        router.refresh();
      } else {
        setError("Invalid token. Please try again.");
      }
    } catch {
      setError("Connection error. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg-primary flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="bg-bg-card border border-border-primary rounded-xl p-8">
          <h1 className="text-2xl font-bold text-text-primary text-center mb-2">
            AI Predicted Wins
          </h1>
          <p className="text-text-muted text-center text-sm mb-8">
            Enter your dashboard token to continue
          </p>

          <form onSubmit={handleSubmit}>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Dashboard token"
              className="w-full px-4 py-3 bg-bg-input border border-border-primary rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-blue transition-colors"
              autoFocus
            />

            {error && (
              <p className="text-loss-red text-sm mt-2">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading || !token}
              className="w-full mt-4 px-4 py-3 bg-accent-blue text-white font-medium rounded-lg hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Authenticating..." : "Sign In"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
