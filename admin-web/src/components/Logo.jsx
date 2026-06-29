import { useState } from 'react';

/// Renders /logo.png (drop it in public/), falling back to a styled "RepLiT"
/// wordmark — white with an orange "LiT" — if the asset is missing.
export default function Logo({ height = 56 }) {
  const [ok, setOk] = useState(true);
  if (ok) {
    return (
      <img
        src="/logo.png"
        alt="RepLiT"
        style={{ height, display: 'block' }}
        onError={() => setOk(false)}
      />
    );
  }
  return (
    <div className="logo-text" style={{ fontSize: height * 0.5 }}>
      Rep<span>LiT</span>
    </div>
  );
}
