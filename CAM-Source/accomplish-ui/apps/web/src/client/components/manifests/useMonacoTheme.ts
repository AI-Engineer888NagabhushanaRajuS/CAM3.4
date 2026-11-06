import { useEffect, useState } from 'react';

const isDark = () => document.documentElement.classList.contains('dark');

/** 'vs-dark' or 'light', following the app's `dark` class on <html> (the theme toggle flips it). */
export function useMonacoTheme(): 'vs-dark' | 'light' {
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const obs = new MutationObserver(() => setDark(isDark()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);
  return dark ? 'vs-dark' : 'light';
}
