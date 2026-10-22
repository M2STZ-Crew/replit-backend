import { useEffect, useState } from 'react';

import { getSoundSettings, subscribeSoundSettings } from '../sound/cues.js';

/// The notification-sound settings (Section 2.8), re-rendering on change. The
/// controls themselves are on the Settings page (pages/Settings.jsx).
export function useSoundSettings() {
  const [settings, setSettings] = useState(getSoundSettings);
  useEffect(() => subscribeSoundSettings(setSettings), []);
  return settings;
}
