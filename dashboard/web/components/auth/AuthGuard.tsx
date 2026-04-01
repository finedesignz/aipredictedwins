"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Skip auth check on login page
    if (pathname === "/login") {
      setChecked(true);
      setAuthenticated(true);
      return;
    }

    fetch("/api/auth/check")
      .then((res) => res.json())
      .then((data) => {
        if (data.authenticated) {
          setAuthenticated(true);
        } else {
          router.push("/login");
        }
        setChecked(true);
      })
      .catch(() => {
        // If auth check fails, allow access (auth might be disabled)
        setAuthenticated(true);
        setChecked(true);
      });
  }, [pathname, router]);

  if (!checked) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center">
        <div className="text-text-muted">Loading...</div>
      </div>
    );
  }

  if (!authenticated) {
    return null;
  }

  return <>{children}</>;
}
