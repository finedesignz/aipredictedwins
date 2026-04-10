interface ErrorBannerProps {
  error: string | null;
}

export default function ErrorBanner({ error }: ErrorBannerProps) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="rounded-lg border border-loss-red/40 bg-loss-red/10 px-4 py-3"
    >
      <p className="text-sm text-loss-red">Error loading data: {error}</p>
    </div>
  );
}
