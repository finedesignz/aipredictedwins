"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Briefcase,
  History,
  BarChart3,
  ShieldAlert,
  Settings,
  TrendingUp,
  Menu,
  X,
} from "lucide-react";
import { useState } from "react";
import ModeBadge from "@/components/shared/ModeBadge";
import { formatCurrencyUnsigned } from "@/lib/format";

const navLinks = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/positions", label: "Positions", icon: Briefcase },
  { href: "/trades", label: "Trades", icon: History },
  { href: "/signals", label: "Signals", icon: BarChart3 },
  { href: "/risk-gate", label: "Risk Gate", icon: ShieldAlert },
  { href: "/settings", label: "Settings", icon: Settings },
];

interface TopNavProps {
  mode?: string;
  equity?: number;
}

export default function TopNav({ mode = "paper", equity = 0 }: TopNavProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <nav
      className="sticky top-0 z-50 border-b border-border-primary bg-bg-card/95 backdrop-blur-sm"
      role="navigation"
      aria-label="Main navigation"
    >
      <div className="mx-auto max-w-7xl px-4">
        <div className="flex h-14 items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-accent-blue" aria-hidden="true" />
            <span className="text-sm font-semibold text-text-primary hidden sm:inline">
              AI Predicted Wins
            </span>
          </div>

          {/* Desktop nav links */}
          <div className="hidden md:flex items-center gap-1">
            {navLinks.map(({ href, label, icon: Icon }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                    active
                      ? "bg-accent-blue/15 text-accent-blue"
                      : "text-text-secondary hover:text-text-primary hover:bg-bg-card-hover"
                  }`}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
          </div>

          {/* Right section */}
          <div className="flex items-center gap-3">
            <ModeBadge mode={mode} />
            <span className="font-mono-nums text-sm font-semibold text-text-primary hidden sm:inline">
              {formatCurrencyUnsigned(equity)}
            </span>

            {/* Mobile menu button */}
            <button
              className="md:hidden p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-card-hover"
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-expanded={mobileOpen}
              aria-label="Toggle navigation menu"
            >
              {mobileOpen ? (
                <X className="h-5 w-5" aria-hidden="true" />
              ) : (
                <Menu className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-border-primary bg-bg-card">
          <div className="px-4 py-2 space-y-1">
            {navLinks.map(({ href, label, icon: Icon }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-2 rounded-md px-3 py-2.5 text-sm transition-colors ${
                    active
                      ? "bg-accent-blue/15 text-accent-blue"
                      : "text-text-secondary hover:text-text-primary hover:bg-bg-card-hover"
                  }`}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {label}
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </nav>
  );
}
